"""Extract structured busway data from an SLD drawing with Claude."""

import json
import logging
from pathlib import Path

from app.config import settings
from app.schemas.boq import BusRun, DrawingExtraction
from app.services.claude_client import ClaudeError, create_message
from app.services.price_list import resolve_frame_rating

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert electrical engineer specialising in busduct and busway systems for the Malaysian market. Read the supplied single-line drawing and extract structured Mikro Busway data.

Rules:
1. First identify transformer-to-MSB busduct as TX-MSB. Then classify each riser as MSB-Riser when it starts at an MSB flange, otherwise RISER when cable-fed.
2. Read nominal current and use the next standard frame in [200, 400, 630, 800, 1000, 1250, 1600, 2000, 2500, 3200, 4000, 5000].
3. Use the shown earth percentage. If missing, default to 50 and flag it.
4. Read AL or CU. If missing, default to AL and flag it.
5. List PIU ratings and flag missing interrupting ratings.
6. Read lengths where shown; otherwise use null and flag them.
7. Estimate hangers only when length is available, using 1.5 m typical spacing.
8. Flag every uncertain or assumed value.

Return only one valid JSON object matching the application schema. run_type must be TX-MSB, MSB-Riser, or RISER."""


def read_drawing(drawing_path: Path) -> DrawingExtraction:
    response = create_message(
        prompt=(
            "Read this single-line drawing using the two-pass method. "
            "Extract every busway run and return only the required JSON object."
        ),
        system_prompt=SYSTEM_PROMPT,
        file_path=drawing_path,
        max_tokens=settings.claude_max_tokens,
    )
    raw_text = response["text"].strip()
    if not raw_text:
        raise ClaudeError("Claude returned an empty drawing analysis.")

    try:
        data = _parse_json_object(raw_text)
        runs = []
        for item in data.get("runs", []):
            item["frame_rating_a"] = resolve_frame_rating(item.get("rating_a", 200))
            item.setdefault("needs_bimetal", item.get("material", "AL") == "AL")
            runs.append(BusRun(**item))
        return DrawingExtraction(
            runs=runs,
            global_flags=data.get("global_flags", []),
            raw_notes=data.get("raw_notes", ""),
        )
    except (json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
        logger.exception(
            "Claude drawing response was invalid request_id=%s",
            response.get("request_id"),
        )
        raise ClaudeError(
            "Claude returned an invalid drawing analysis. Please try again."
        ) from exc


def _parse_json_object(text: str) -> dict:
    cleaned = text.strip()
    fence = chr(96) * 3
    if cleaned.startswith(fence):
        lines = cleaned.splitlines()
        cleaned = "\n".join(
            lines[1:-1] if lines[-1].strip() == fence else lines[1:]
        )

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise json.JSONDecodeError("No JSON object found", cleaned, 0)

    parsed = json.loads(cleaned[start : end + 1])
    if not isinstance(parsed, dict):
        raise TypeError("Claude response must be a JSON object")
    return parsed
