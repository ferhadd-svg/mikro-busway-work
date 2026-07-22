"""
Send an SLD drawing to Claude and extract busway run data.

Two-pass method (per Mikro Busway rules):
  Pass 1 — Find TX/transformer → TX-MSB run
  Pass 2 — Find risers → classify MSB-Riser vs RISER (cable-entry)

Returns DrawingExtraction (structured runs + flags).
"""

import base64
import json
import math
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

SYSTEM_PROMPT = """You are an expert electrical engineer specialising in busduct/busway systems for the Malaysian market (Mikro Busway). You read single-line drawings (SLD) and extract structured busway data. The drawing may be supplied as a full-sheet overview plus several high-resolution tiles that together cover the same sheet — use the tiles to read small labels and the overview to understand how runs connect.

CRITICAL RULES — read every one before responding:

0. FIRST CHECK THE SHEET IS AN SLD. Many uploads are NOT single-line diagrams:
   - Rate/price docs: Schedule of Unit Rates, Bill of Quantities, Load Schedule, cable schedule, spec/notes page (tables of "Description/Unit/Price", ampere lists with RM prices).
   - Architectural/other drawings: a FLOOR PLAN, socket/lighting LAYOUT, building ELEVATION, SECTION, or site plan (these ARE drawings but have no single-line runs).
   - HT/MV-only sheets: a 33kV/11kV switchgear SLD (VCBs, CTs, PTs, protection relays, TNB incoming, GIS/AIS) has NO busduct — busduct is on the LV distribution sheet. Return no runs and flag "HT/MV switchgear sheet — busduct is on the LV single-line, not this page."
   In multi-page sets the first page is often a cover, elevation, layout, or HT sheet — the LV busduct SLD may be on a later page.
   If the sheet shown is not a single-line schematic, return "runs": [] and add a global_flag naming what it is, e.g. "This sheet is a <floor plan / elevation / rate schedule>, not an SLD — no busduct runs extracted (check the other pages for the single-line diagram)." Do NOT invent runs.

1. QUOTE BUSDUCT ONLY — NOT CABLE. This is the most important rule.
   - A run is BUSDUCT (busway) only if its label says so, e.g. "1250A TPN ALU. BUSDUCT", "600A TPN 3 PHASE ALU. BUSDUCT", "2000A TPN CU BUSDUCT", "BUSWAY", "BUS TRUNKING". The word may sit on its own line with the ampere value just above or below it (e.g. "BUSDUCT" with "1,000 A" underneath) — read them together. Quote these.
   - A run is CABLE if labelled like "6 NOS 4 x 400mm² 1C XLPE/PVC ALU. CABLE", "4 x 240mm.sq ... CABLE", "NYY 4 x ...", "... IN TRUNKING/ON CABLE TRAY". Cables also feed DBs, SSBs, machines, pumps, EV chargers, lifts. DO NOT quote cable — ignore it completely.
   - The BUSBARS INSIDE a switchboard are NOT busduct — e.g. "400V 2000A TPN ... SLEEVED TINNED COPPER BUSBARS", "busbar chamber". Only quote busduct that RUNS BETWEEN boards/levels (labelled "... BUSDUCT"/"BUSWAY"), never a board's internal busbar.
   - Read the label on EACH connection to decide. Never assume by position.

2. TX→MSB CAN BE EITHER BUSDUCT OR CABLE — you must check.
   - Some projects run the transformer→MSB feed (and genset→MSB, and MSB↔MSB bus-tie/bus-coupler) as busduct ("BUSDUCT 1,000 A", "BUSDUCT 630 A"): quote each as a run. A horizontal TX→MSB / genset→MSB / bus-tie busduct is a "TX-MSB" type (flange-end feeder accessories).
   - Others run the TX→MSB feed as cable ("N NOS 4 x 400mm² ... CABLE"): ignore it.
   - Decide strictly from the connection's own label, not from the fact that it is a TX→MSB link.

3. RATING — read the BUSDUCT label, never the breaker or CT.
   - The busduct rating is the ampere value printed ON the busduct run itself (e.g. "1250A TPN ALU. BUSDUCT" → 1250A; "BUSDUCT" over "1,000 A" → 1000A).
   - DO NOT use the ACB/MCCB frame size (e.g. "2000A TPN ACB", "1600AF") — that is the breaker, not the busduct.
   - DO NOT use a CT ratio (e.g. "2000/5A CT", "CL5P10", "600/5A") — that is metering, not the busduct.
   - If a busduct run has no ampere label of its own and the only nearby numbers are an ACB frame or CT ratio, set rating_a to null and add a flag "busduct rating not labelled — only ACB/CT visible, needs confirmation". Do NOT guess from the breaker/CT.
   - frame_rating = the next standard frame in [200,400,630,800,1000,1250,1600,2000,2500,3200,4000,5000] (e.g. 500→630, 100→200). A busduct already labelled 1250A stays 1250A.

4. RUN TYPE & ROUTING — classify each busduct run by where it starts:
   - Transformer LV side → MSB, as busduct → type "TX-MSB", routing "FROM TX-n TO MSB-n". (Also genset→MSB and MSB↔MSB bus-tie busduct → "TX-MSB".)
   - Starts at an MSB flange end (goes up the building) → type "MSB-Riser", routing "FROM MSB-n TO LEVEL n".
   - Starts at a cable feed-in / joint box / termination box → type "RISER", routing "FROM LEVEL x TO LEVEL y".
   - A building often has SEVERAL separate riser busducts — by code (R-A/CB-R, R-B/CB-R) or by supply function ("NORMAL SUPPLY BUSDUCT RISER", "ESSENTIAL SUPPLY BUSDUCT RISER", EMSB emergency riser) — each running up its own levels. Extract EACH as its own run, named as labelled. Do not merge them.
   - Use the actual board/level/riser names printed on the drawing (MSB-T1, EMSB, R-A/CB-R, NORMAL/ESSENTIAL SUPPLY RISER, SSB/L12, LEVEL 7, ROOF, etc.).

5. MATERIAL — read "ALU/AL" or "CU/COPPER" from the busduct label. If absent, default AL and flag.

6. EARTH % / PHASES
   - Earth: shown "50%E"/"+50%E" → 50%E; "100%E"/"+100% EARTH"/"100% ELECTRICAL" → 100%E. "1/2 earth" = 50%E. "100% neutral + integral earth" → still 4W+50%E. "+E" / "+ E" / "c/w integral earth" means earth is integral (a feeder always has it) — NOT a 100% earth; still default 50%E unless a % is given. Not shown → default 50%E and flag.
   - Phases: "3P4W" or "TPN" or "4P"/"4 POLE" all mean 4-wire → phases "3P4W". "3P5W"/"5W" → phases "3P5W" and flag "3P5W — price on 5W feeder column".

7. PIU (plug-in units on a riser) — list each plug-in/tap-off MCCB rating shown along the run (e.g. 100A, 250A, 400A TPN). If the kA interrupting rating isn't shown, flag it (default 26kA).

8. LENGTHS — an SLD does NOT show physical run length. Set length_m to null and flag "length not on SLD — needs layout/section or user estimate" unless a length is explicitly dimensioned.

9. HANGERS — leave num_fixed_hangers/num_spring_hangers null when length is unknown (they are computed later).

10. FLAGS — add a plain-English flag for every uncertain, missing, or assumed value. When unsure about a rating, FLAG IT rather than guessing.

Respond with ONLY a JSON object — no markdown fences, no commentary. Schema:
{
  "runs": [
    {
      "run_id": "RUN-1",
      "run_type": "TX-MSB" | "MSB-Riser" | "RISER",
      "rating_a": <int busduct rating, or null if only ACB/CT visible>,
      "frame_rating_a": <int frame>,
      "material": "AL" | "CU",
      "earth_pct": 50 | 100,
      "routing": "<string, e.g. FROM MSB-T1 TO LEVEL 7>",
      "phases": "3P4W" | "3P5W",
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
            # PDFs default to 72 DPI; render at ~220 DPI so small busduct/ACB
            # labels survive. The page is tiled afterwards, so a big raster is
            # fine — it is never sent to the model whole at this size.
            pix = page.get_pixmap(matrix=fitz.Matrix(220 / 72, 220 / 72))
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


# Claude vision keeps full detail up to ~1568 px on the long edge and
# downscales anything larger server-side. A dense A0/A1 SLD is far larger, so
# sending it as one image (the old behaviour) blurred every rating label. We
# instead send a downscaled OVERVIEW (for global layout/routing) plus a grid
# of high-resolution TILES (so each small label is read at full detail).
_VISION_MAX_PX = 1568
_TILE_TARGET_PX = 1500     # aim for tiles around this long-edge
_TILE_OVERLAP = 0.10       # 10% overlap so labels on a seam aren't split
_MAX_TILES = 15            # cap total tiles per page to bound cost/latency


def _downscale(image_path: Path, max_px: int = _VISION_MAX_PX) -> Path:
    """Return a copy scaled so the longest side ≤ max_px (or the original if
    already small enough)."""
    img = Image.open(image_path)
    w, h = img.size
    if max(w, h) <= max_px:
        return image_path
    ratio = max_px / max(w, h)
    out = image_path.with_stem(image_path.stem + "_overview")
    img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS).save(out)
    return out


def _tile_image(image_path: Path, max_tiles: int = _MAX_TILES) -> list[Path]:
    """Split a large image into an overlapping grid of tiles, each roughly
    _TILE_TARGET_PX on the long edge, so text stays legible after the model's
    server-side downscale. Returns [] for images small enough to send whole."""
    img = Image.open(image_path)
    W, H = img.size
    if max(W, H) <= _VISION_MAX_PX:
        return []

    cols = max(1, math.ceil(W / _TILE_TARGET_PX))
    rows = max(1, math.ceil(H / _TILE_TARGET_PX))
    # Bound the tile count (very large sheets → coarser tiles).
    while cols * rows > max_tiles:
        if cols >= rows and cols > 1:
            cols -= 1
        elif rows > 1:
            rows -= 1
        else:
            break

    tw, th = W / cols, H / rows
    ox, oy = tw * _TILE_OVERLAP, th * _TILE_OVERLAP
    tiles: list[Path] = []
    for r in range(rows):
        for c in range(cols):
            left = max(0, int(c * tw - ox))
            top = max(0, int(r * th - oy))
            right = min(W, int((c + 1) * tw + ox))
            bottom = min(H, int((r + 1) * th + oy))
            crop = img.crop((left, top, right, bottom))
            out = image_path.with_stem(f"{image_path.stem}_t{r}_{c}")
            crop.save(out)
            tiles.append(out)
    return tiles


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

    # For each page: a downscaled OVERVIEW (global layout/routing) + high-res
    # TILES (legible labels). Split the tile budget across pages.
    per_page_tiles = max(2, _MAX_TILES // max(1, len(image_paths)))
    prepared: list[tuple[str, Path]] = []
    for idx, page_path in enumerate(image_paths, 1):
        tag = f"page {idx} of {len(image_paths)}" if len(image_paths) > 1 else "full sheet"
        prepared.append((f"OVERVIEW ({tag}) — use for how runs connect:", _downscale(page_path)))
        tiles = _tile_image(page_path, max_tiles=per_page_tiles)
        for j, tile in enumerate(tiles, 1):
            prepared.append((f"DETAIL TILE {j}/{len(tiles)} ({tag}) — read labels here:", tile))

    if not settings.anthropic_api_key:
        raise RuntimeError(
            "No Anthropic API key set. Add ANTHROPIC_API_KEY to your .env file, "
            "or use Manual Entry mode instead."
        )
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    content = []
    for label, path in prepared:
        content.append({"type": "text", "text": label})
        b64_data, media_type = _image_to_b64(path)
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
        "text": "The overview and tiles above are the SAME single-line drawing. "
                "Extract every BUSDUCT run (ignore all cable). Read ratings from the "
                "busduct labels only — never from an ACB frame size or CT ratio. "
                "Return the JSON object.",
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
