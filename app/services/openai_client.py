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


class OpenAIError(RuntimeError):
    """Base error for safe OpenAI integration failures."""


class OpenAIConfigurationError(OpenAIError):
    """Raised when OpenAI credentials or local dependencies are invalid."""


class OpenAIFileError(OpenAIError):
    """Raised when an uploaded file cannot be sent safely to OpenAI."""


def is_configured() -> bool:
    return bool(settings.openai_api_key)


def get_client() -> Any:
    if not settings.openai_api_key:
        raise OpenAIConfigurationError(
            "OPENAI_API_KEY is not configured. Add it in Render Environment Variables."
        )

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise OpenAIConfigurationError(
            "The openai package is not installed. Run pip install -r requirements.txt."
        ) from exc

    return OpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_timeout_seconds,
        max_retries=settings.openai_max_retries,
    )


def validate_supported_file(path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_FILE_SUFFIXES:
        allowed = ", ".join(sorted(SUPPORTED_FILE_SUFFIXES))
        raise OpenAIFileError(f"Unsupported file type '{suffix}'. Allowed: {allowed}")
    size = path.stat().st_size
    if size <= 0:
        raise OpenAIFileError("Uploaded file is empty.")
    if size > settings.openai_max_file_bytes:
        raise OpenAIFileError(
            f"Uploaded file is {size} bytes. Limit is OPENAI_MAX_FILE_BYTES="
            f"{settings.openai_max_file_bytes}."
        )


def file_content_block(path: Path) -> dict[str, Any]:
    validate_supported_file(path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return {
            "type": "input_file",
            "filename": path.name,
            "file_data": f"data:application/pdf;base64,{_b64(path.read_bytes())}",
        }

    image_bytes, media_type = _prepare_image(path)
    return {
        "type": "input_image",
        "image_url": f"data:{media_type};base64,{_b64(image_bytes)}",
    }


def create_response(
    *,
    prompt: str,
    system_prompt: str | None = None,
    file_path: Path | None = None,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    if not prompt.strip():
        raise OpenAIError("Prompt is required.")

    content: list[dict[str, Any]] = []
    if file_path:
        content.append(file_content_block(file_path))
    content.append({"type": "input_text", "text": prompt.strip()})

    request: dict[str, Any] = {
        "model": settings.openai_model,
        "input": [{"role": "user", "content": content}],
        "max_output_tokens": max_output_tokens or settings.openai_max_output_tokens,
    }
    if system_prompt:
        request["instructions"] = system_prompt

    try:
        response = get_client().responses.create(**request)
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        request_id = getattr(exc, "request_id", None)
        error_name = type(exc).__name__
        logger.exception(
            "OpenAI request failed status=%s request_id=%s", status_code, request_id
        )
        if error_name == "AuthenticationError" or status_code == 401:
            raise OpenAIConfigurationError(
                "OpenAI rejected the API key. Replace OPENAI_API_KEY in Render."
            ) from exc
        if error_name == "PermissionDeniedError" or status_code == 403:
            raise OpenAIConfigurationError(
                "The OpenAI API project cannot use the configured model."
            ) from exc
        if error_name == "RateLimitError" or status_code == 429:
            raise OpenAIError(
                "OpenAI rate or billing limit reached. Check the Platform billing page."
            ) from exc
        if error_name in {"APIConnectionError", "APITimeoutError"}:
            raise OpenAIError(
                "Could not connect to OpenAI after retries. Check Render logs and retry."
            ) from exc
        raise OpenAIError(
            "OpenAI API request failed. Check Render logs for details."
        ) from exc

    usage = getattr(response, "usage", None)
    return {
        "model": getattr(response, "model", settings.openai_model),
        "request_id": getattr(response, "_request_id", None),
        "response_id": getattr(response, "id", None),
        "status": getattr(response, "status", None),
        "usage": {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        },
        "text": str(getattr(response, "output_text", "") or "").strip(),
    }


def ping() -> dict[str, Any]:
    return create_response(
        prompt="Reply with exactly: OK",
        system_prompt="You are a connection health check. Keep the response minimal.",
        max_output_tokens=32,
    )


def _prepare_image(path: Path) -> tuple[bytes, str]:
    suffix = path.suffix.lower()
    original_media_type = IMAGE_MEDIA_TYPES.get(suffix, "image/png")

    try:
        from PIL import Image
    except ImportError as exc:
        raise OpenAIConfigurationError("Pillow is required for image handling.") from exc

    with Image.open(path) as image:
        image.load()
        width, height = image.size
        should_resize = max(width, height) > settings.openai_max_image_px
        needs_conversion = suffix not in IMAGE_MEDIA_TYPES or suffix in {".tif", ".tiff"}

        if not should_resize and not needs_conversion:
            return path.read_bytes(), original_media_type

        if should_resize:
            ratio = settings.openai_max_image_px / max(width, height)
            image = image.resize((int(width * ratio), int(height * ratio)), Image.LANCZOS)

        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGB")

        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue(), "image/png"


def _b64(data: bytes) -> str:
    return base64.standard_b64encode(data).decode("utf-8")
