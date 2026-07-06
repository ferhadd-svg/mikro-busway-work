"""
Send an SLD drawing to Claude and extract busway run data.

Two-pass method (per Mikro Busway rules):
  Pass 1 — Find TX/transformer → TX-MSB run
  Pass 2 — Find risers → classify MSB-Riser vs RISER (cable-entry)

Returns DrawingExtraction (structured runs + flags).
"""

import base64
import json
import re
from pathlib import Path
from typing import Optional

import anthropic
from PIL import Image
from pydantic import ValidationError

try:  # PyMuPDF renders PDF pages to images with no system tools (works on Render)
    import pymupdf as fitz
except ImportError:  # older PyMuPDF versions expose the module as "fitz"
    import fitz

from app.config import settings
from app.schemas.boq import DrawingExtraction, BusRun
from app.services.price_list import resolve_frame_rating

SYSTEM_PROMPT = """You are an expert electrical engineer specialising in busduct/busway systems for the Malaysian market (Mikro Busway). You read single-line drawings (SLD) and extract structured busway data.

CRITICAL RULES — read every one before responding:

1. TWO-PASS METHOD
   Pass 1: Find the TX/transformer first → any busduct connected to the TX LV side is a TX-MSB run.
   Pass 2: Find all riser busducts → classify by WHERE they start:
     - Starts at MSB flange end → type = "MSB-Riser", routing "FROM MSB TO <level>"
     - Starts at cable entry / joint box / termination box / flange end box (cable-fed) → type = "RISER", routing "FROM <level> TO <level>"

2. RATINGS
   - Read the NOMINAL rating from the drawing label (e.g. "500A" → nominal=500).
   - Compute frame_rating: use the next standard frame in [200,400,630,800,1000,1250,1600,2000,2500,3200,4000,5000].
     Example: 500A nominal → 630A frame; 100A nominal → 200A frame.

3. EARTH PERCENTAGE
   - If a % is shown (e.g. "50%E", "100%E") → use it.
   - If NOT shown → default to 50%E and add a flag "earth_pct not shown on drawing, defaulted to 50%E".

4. MATERIAL
   - Read "AL" or "CU" from the drawing label.
   - If not stated → add a flag "material not shown, needs confirmation" and default to AL.

5. PIU
   - List each PIU (plug-in unit) rating shown along the run (e.g. 60A TPN MCCB, 150A TPN MCCB).
   - If the kA interrupting rating is not shown, flag it.

6. LENGTHS
   - Read feeder lengths from the drawing if shown (from elevation or floor-to-floor dimensions).
   - If NOT readable → set length_m to null and add a flag.

7. HANGERS
   - Estimate fixed/spring hanger quantities from the run length if given (typical spacing: 1.5m fixed, alternate spring).
   - If length not known, set both to null and flag.

8. FLAGS
   - Add a flag for every uncertain or missing value.
   - Flag format: plain English string describing what is missing and what was assumed.

Respond with ONLY a JSON object — no markdown fences, no commentary. Schema:
{
  "runs": [
    {
      "run_id": "RUN-1",
      "run_type": "TX-MSB" | "MSB-Riser" | "RISER",
      "rating_a": <int nominal>,
      "frame_rating_a": <int frame>,
      "material": "AL" | "CU",
      "earth_pct": 50 | 100,
      "routing": "<string>",
      "phases": "3P4W",
      "length_m": <float or null>,
      "hanger_spacing_m": 1.5,
      "num_fixed_hangers": <int or null>,
      "num_spring_hangers": <int or null>,
      "piu_ratings": [<int>, ...],
      "spare_openings": <int>,
      "needs_bimetal": <bool, true if AL>,
      "flags": ["<flag text>", ...]
    }
  ],
  "global_flags": ["<flag text>", ...],
  "raw_notes": "<any additional observations>"
}"""


# SLDs regularly span more than one sheet; send Claude up to this many pages.
MAX_PDF_PAGES = 4


def _pdf_to_images(pdf_path: Path, max_pages: int = MAX_PDF_PAGES) -> tuple[list[Path], int]:
    """Rasterize up to max_pages PDF pages to PNGs using PyMuPDF (no system deps).
    Returns (image_paths, total_page_count)."""
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        raise RuntimeError(f"Could not open the PDF drawing: {e}")
    try:
        total_pages = doc.page_count
        if total_pages == 0:
            raise RuntimeError("The PDF drawing has no pages.")
        paths = []
        for i in range(min(total_pages, max_pages)):
            page = doc.load_page(i)
            # PDFs default to 72 DPI; zoom to ~150 DPI for a legible raster.
            pix = page.get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72))
            out_path = pdf_path.with_name(f"{pdf_path.stem}_p{i + 1}.png")
            pix.save(str(out_path))
            paths.append(out_path)
    finally:
        doc.close()
    return paths, total_pages


def _ensure_supported_image(image_path: Path) -> Path:
    """Claude vision accepts jpeg/png/gif/webp. Convert anything else
    (e.g. TIFF) to PNG so every uploaded image works."""
    if image_path.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        return image_path
    img = Image.open(image_path)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    out_path = image_path.with_suffix(".png")
    img.save(out_path, "PNG")
    return out_path


def _image_to_b64(image_path: Path) -> tuple[str, str]:
    """Return (base64_data, media_type)."""
    suffix = image_path.suffix.lower()
    media_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_map.get(suffix, "image/png")
    with open(image_path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode()
    return data, media_type


def _resize_if_needed(image_path: Path, max_px: int = 1568) -> Path:
    """Resize image so longest side ≤ max_px. Returns path (may be new file).
    Claude vision downscales anything above 1568 px server-side anyway, so
    resizing locally saves upload time with no loss in what the model sees."""
    img = Image.open(image_path)
    w, h = img.size
    if max(w, h) <= max_px:
        return image_path
    ratio = max_px / max(w, h)
    new_size = (int(w * ratio), int(h * ratio))
    img_resized = img.resize(new_size, Image.LANCZOS)
    out_path = image_path.with_stem(image_path.stem + "_resized")
    img_resized.save(out_path)
    return out_path


def _parse_json_response(raw_text: str) -> Optional[dict]:
    """Parse Claude's reply into a dict, tolerating markdown fences and prose."""
    raw_text = raw_text.strip()

    # Strip accidental markdown fences (``` or ```json ... ```)
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")[1:]                 # drop opening ``` / ```json
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]                           # drop closing ```
        raw_text = "\n".join(lines).strip()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        # If the model wrapped the JSON in prose, extract the {...} object.
        start, end = raw_text.find("{"), raw_text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            data = json.loads(raw_text[start:end + 1])
        except json.JSONDecodeError:
            return None

    return data if isinstance(data, dict) else None


_RUN_TYPES = {"tx-msb": "TX-MSB", "msb-riser": "MSB-Riser", "riser": "RISER"}


def _normalise_run(r: dict, index: int) -> dict:
    """Coerce a raw run dict from Claude into the shapes BusRun expects,
    flagging what had to be assumed instead of failing the whole read."""
    r = dict(r)
    flags = [str(f) for f in (r.get("flags") or [])]

    r.setdefault("run_id", f"RUN-{index}")
    r.setdefault("routing", "")

    # Nominal rating: default 200A when unreadable, and always recompute the
    # frame rating locally rather than trusting the model's arithmetic.
    try:
        nominal = int(float(r.get("rating_a")))
    except (TypeError, ValueError):
        nominal = 200
        flags.append("rating not readable on drawing; assumed 200A — please confirm")
    r["rating_a"] = nominal
    r["frame_rating_a"] = resolve_frame_rating(nominal)

    material = str(r.get("material") or "AL").strip().upper()
    if material.startswith("CU") or "COPPER" in material:
        material = "CU"
    else:
        if material != "AL" and not material.startswith("AL"):
            flags.append(f"material '{r.get('material')}' not recognised; assumed AL")
        material = "AL"
    r["material"] = material

    try:
        earth = int(float(r.get("earth_pct")))
    except (TypeError, ValueError):
        earth = 50
        flags.append("earth % not readable; defaulted to 50%E")
    if earth not in (50, 100):
        snapped = 50 if earth <= 50 else 100
        flags.append(f"earth {earth}%E is not a standard option; used {snapped}%E")
        earth = snapped
    r["earth_pct"] = earth

    run_type = _RUN_TYPES.get(str(r.get("run_type") or "").strip().lower())
    if run_type is None:
        run_type = "RISER"
        flags.append(f"run type '{r.get('run_type')}' not recognised; treated as RISER")
    r["run_type"] = run_type

    piu_ratings = []
    for p in (r.get("piu_ratings") or []):
        try:
            piu_ratings.append(int(float(p)))
        except (TypeError, ValueError):
            m = re.search(r"\d+", str(p))       # e.g. "60A TPN MCCB" → 60
            if m:
                piu_ratings.append(int(m.group()))
            else:
                flags.append(f"PIU rating '{p}' not understood; ignored")
    r["piu_ratings"] = piu_ratings

    # Drop explicit nulls where BusRun has a non-null default
    for key in ("phases", "hanger_spacing_m", "spare_openings", "needs_bimetal"):
        if r.get(key) is None:
            r.pop(key, None)

    r.setdefault("needs_bimetal", material == "AL")
    r["flags"] = flags
    return r


def read_drawing(drawing_path: Path) -> DrawingExtraction:
    """
    Main entry point. Accepts PDF (multi-page) or image file.
    Calls Claude with vision and returns a DrawingExtraction.
    """
    # Convert PDF → images; normalise other image formats (TIFF etc.) to PNG
    total_pages = 1
    if drawing_path.suffix.lower() == ".pdf":
        image_paths, total_pages = _pdf_to_images(drawing_path)
    else:
        image_paths = [_ensure_supported_image(drawing_path)]

    image_paths = [_resize_if_needed(p) for p in image_paths]

    if not settings.anthropic_api_key:
        raise RuntimeError(
            "No Anthropic API key set. Add ANTHROPIC_API_KEY to your .env file, "
            "or use Manual Entry mode instead."
        )
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    content = []
    for idx, image_path in enumerate(image_paths, 1):
        if len(image_paths) > 1:
            content.append({"type": "text", "text": f"Drawing page {idx} of {len(image_paths)}:"})
        b64_data, media_type = _image_to_b64(image_path)
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": b64_data,
            },
        })
    content.append({
        "type": "text",
        "text": "Read this single-line drawing (all pages shown above) and extract all "
                "busway runs using the two-pass method. Return the JSON object.",
    })

    try:
        message = client.messages.create(
            model=settings.claude_model,
            max_tokens=8192,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.AuthenticationError:
        raise RuntimeError(
            "Anthropic rejected the API key (invalid key). In Render, open the "
            "work-16 service > Environment and set ANTHROPIC_API_KEY to a valid key "
            "from console.anthropic.com (paste the whole key, no spaces or quotes). "
            "Or switch to Manual Entry mode, which needs no API key."
        )
    except anthropic.RateLimitError:
        raise RuntimeError(
            "Anthropic returned a rate-limit / no-credit error. Add billing credit at "
            "console.anthropic.com > Billing, then try again. Or use Manual Entry mode."
        )
    except anthropic.APIConnectionError:
        raise RuntimeError(
            "Could not reach the Anthropic API (network problem). Check the server's "
            "internet connection and try again, or use Manual Entry mode."
        )
    except anthropic.APIStatusError as e:
        raise RuntimeError(
            f"Anthropic API error ({e.status_code}). Please try again shortly, "
            f"or use Manual Entry mode. Details: {e.message}"
        )

    if message.stop_reason == "max_tokens":
        raise RuntimeError(
            "Claude's reply was cut off before it finished — the drawing may have "
            "too many runs to read in one pass. Try again, or use Manual Entry."
        )

    # Pull the text block out of the response (guard against empty/other blocks)
    raw_text = ""
    for block in message.content:
        if getattr(block, "type", None) == "text":
            raw_text = block.text
            break

    data = _parse_json_response(raw_text)
    if data is None:
        snippet = raw_text.strip()[:300] if raw_text.strip() else "(empty response)"
        raise RuntimeError(
            "Claude could not turn this drawing into structured data. This usually "
            "means the drawing was unclear, too low-resolution, or not a single-line "
            "diagram. Try a clearer or larger image, or use Manual Entry. "
            f"[Claude replied: {snippet}]"
        )

    global_flags = [str(f) for f in (data.get("global_flags") or [])]
    if total_pages > len(image_paths):
        global_flags.append(
            f"The PDF has {total_pages} pages but only the first {len(image_paths)} "
            f"were read. Check the remaining pages for additional runs."
        )

    # One malformed run should not lose the whole drawing: normalise what we
    # can, skip (and flag) what we can't.
    runs = []
    for i, raw_run in enumerate(data.get("runs") or [], 1):
        if not isinstance(raw_run, dict):
            global_flags.append(f"Run #{i} in the AI response was malformed and was skipped.")
            continue
        try:
            runs.append(BusRun(**_normalise_run(raw_run, i)))
        except ValidationError:
            run_id = raw_run.get("run_id") or f"RUN-{i}"
            global_flags.append(
                f"{run_id} could not be read reliably and was skipped. "
                f"Add it via Manual Entry if it exists on the drawing."
            )

    return DrawingExtraction(
        runs=runs,
        global_flags=global_flags,
        raw_notes=str(data.get("raw_notes") or ""),
    )
