"""
Send an SLD drawing to Claude and extract busway run data.

Two-pass method (per Mikro Busway rules):
  Pass 1 — Find TX/transformer → TX-MSB run
  Pass 2 — Find risers → classify MSB-Riser vs RISER (cable-entry)

Returns DrawingExtraction (structured runs + flags).
"""

import base64
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import anthropic
from PIL import Image

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


def _pdf_to_image(pdf_path: Path) -> Path:
    """Rasterize first page of PDF at 150 DPI, return PNG path."""
    out_dir = pdf_path.parent
    prefix = pdf_path.stem
    result = subprocess.run(
        ["pdftoppm", "-r", "150", "-l", "1", "-png", str(pdf_path), str(out_dir / prefix)],
        capture_output=True,
    )
    # pdftoppm produces <prefix>-1.png (or -01.png depending on version)
    candidates = list(out_dir.glob(f"{prefix}*.png"))
    if not candidates:
        raise RuntimeError(f"pdftoppm failed: {result.stderr.decode()}")
    return sorted(candidates)[0]


def _image_to_b64(image_path: Path) -> tuple[str, str]:
    """Return (base64_data, media_type)."""
    suffix = image_path.suffix.lower()
    media_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
    media_type = media_map.get(suffix, "image/png")
    with open(image_path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode()
    return data, media_type


def _resize_if_needed(image_path: Path, max_px: int = 2000) -> Path:
    """Resize image so longest side ≤ max_px. Returns path (may be new file)."""
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


def read_drawing(drawing_path: Path) -> DrawingExtraction:
    """
    Main entry point. Accepts PDF or image file.
    Calls Claude with vision and returns a DrawingExtraction.
    """
    # Convert PDF → image
    if drawing_path.suffix.lower() == ".pdf":
        image_path = _pdf_to_image(drawing_path)
    else:
        image_path = drawing_path

    image_path = _resize_if_needed(image_path)
    b64_data, media_type = _image_to_b64(image_path)

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    message = client.messages.create(
        model=settings.claude_model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Read this single-line drawing and extract all busway runs using the two-pass method. Return the JSON object.",
                    },
                ],
            }
        ],
    )

    raw_text = message.content[0].text.strip()

    # Strip accidental markdown fences
    if raw_text.startswith("```"):
        raw_text = "\n".join(raw_text.split("\n")[1:])
    if raw_text.endswith("```"):
        raw_text = "\n".join(raw_text.split("\n")[:-1])

    data = json.loads(raw_text)

    # Ensure frame_rating_a is set correctly
    runs = []
    for r in data.get("runs", []):
        r["frame_rating_a"] = resolve_frame_rating(r.get("rating_a", 200))
        r.setdefault("needs_bimetal", r.get("material", "AL") == "AL")
        runs.append(BusRun(**r))

    return DrawingExtraction(
        runs=runs,
        global_flags=data.get("global_flags", []),
        raw_notes=data.get("raw_notes", ""),
    )
