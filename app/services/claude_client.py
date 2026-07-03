import base64
import logging
from io import BytesIO
from pathlib import Path
from typing import Any

from app.config import settings


logger = logging.getLogger(__name__)

IMAGE_MEDIA_TYPES = {
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
SUPPORTED_FILE_SUFFIXES = set(IMAGE_MEDIA_TYPES) | {".pdf", ".tif", ".tiff"}


class ClaudeError(RuntimeError):
    """Base error for safe Claude integration failures."""


class ClaudeConfigurationError(ClaudeError):
    """Raised when Anthropic credentials are missing or invalid locally."""


class ClaudeFileError(ClaudeError):
    """Raised when an uploaded file cannot be sent safely to Claude."""


def is_configured() -> bool:
    return bool(settings.anthropic_api_key)


def get_client() -> Any:
    if not settings.anthropic_api_key:
        raise ClaudeConfigurationError(
            "ANTHROPIC_API_KEY is not configured. Add it in Render Environment Variables."
        )

    try:
        import anthropic
    except ImportError as exc:
        raise ClaudeConfigurationError(
            "The anthropic package is not installed. Run pip install -r requirements.txt."
        ) from exc

    return anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        timeout=settings.claude_timeout_seconds,
        max_retries=settings.claude_max_retries,
    )


def validate_supported_file(path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_FILE_SUFFIXES:
        allowed = ", ".join(sorted(SUPPORTED_FILE_SUFFIXES))
        raise ClaudeFileError(f"Unsupported file type '{suffix}'. Allowed: {allowed}")
    size = path.stat().st_size
    if size <= 0:
        raise ClaudeFileError("Uploaded file is empty.")
    if size > settings.claude_max_file_bytes:
        raise ClaudeFileError(
            f"Uploaded file is {size} bytes. Limit is CLAUDE_MAX_FILE_BYTES="
            f"{settings.claude_max_file_bytes}."
        )


def file_content_block(path: Path) -> dict[str, Any]:
    validate_supported_file(path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": _b64(path.read_bytes()),
            },
        }

    image_bytes, media_type = _prepare_image(path)
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": _b64(image_bytes),
        },
    }


def create_message(
    *,
    prompt: str,
    system_prompt: str | None = None,
    file_path: Path | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    if not prompt.strip():
        raise ClaudeError("Prompt is required.")

    content: list[dict[str, Any]] = []
    if file_path:
        content.append(file_content_block(file_path))
    content.append({"type": "text", "text": prompt.strip()})

    client = get_client()
    request: dict[str, Any] = {
        "model": settings.claude_model,
        "max_tokens": max_tokens or settings.claude_max_tokens,
        "messages": [{"role": "user", "content": content}],
    }
    if system_prompt:
        request["system"] = system_prompt

    try:
        message = client.messages.create(**request)
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        request_id = getattr(exc, "request_id", None)
        logger.exception("Claude request failed status=%s request_id=%s", status_code, request_id)
        error_name = type(exc).__name__
        if error_name == "AuthenticationError" or status_code == 401:
            raise ClaudeConfigurationError(
                "Anthropic rejected the API key. Replace ANTHROPIC_API_KEY in Render."
            ) from exc
        if error_name == "PermissionDeniedError" or status_code == 403:
            raise ClaudeConfigurationError(
                "The Anthropic API key does not have permission to use this model."
            ) from exc
        if error_name in {"APIConnectionError", "APITimeoutError"}:
            raise ClaudeError(
                "Could not connect to Anthropic after retries. Check Render logs and retry."
            ) from exc
        raise ClaudeError(
            "Claude API request failed. Check Render logs for details."
        ) from exc

    usage = getattr(message, "usage", None)
    return {
        "model": getattr(message, "model", settings.claude_model),
        "request_id": getattr(message, "_request_id", None),
        "stop_reason": getattr(message, "stop_reason", None),
        "usage": {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        },
        "text": extract_text(message),
    }


def ping() -> dict[str, Any]:
    return create_message(
        prompt="Reply with exactly: OK",
        system_prompt="You are a connection health check. Keep the response minimal.",
        max_tokens=64,
    )


def extract_text(message: Any) -> str:
    parts: list[str] = []
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", ""))
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "\n".join(part for part in parts if part).strip()


def _prepare_image(path: Path) -> tuple[bytes, str]:
    suffix = path.suffix.lower()
    original_media_type = IMAGE_MEDIA_TYPES.get(suffix, "image/png")

    try:
        from PIL import Image
    except ImportError as exc:
        raise ClaudeConfigurationError("Pillow is required for image handling.") from exc

    with Image.open(path) as image:
        image.load()
        width, height = image.size
        should_resize = max(width, height) > settings.claude_max_image_px
        needs_conversion = suffix not in IMAGE_MEDIA_TYPES or suffix in {".tif", ".tiff"}

        if not should_resize and not needs_conversion:
            return path.read_bytes(), original_media_type

        if should_resize:
            ratio = settings.claude_max_image_px / max(width, height)
            image = image.resize((int(width * ratio), int(height * ratio)), Image.LANCZOS)

        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGB")

        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue(), "image/png"


def _b64(data: bytes) -> str:
    return base64.standard_b64encode(data).decode("utf-8")

