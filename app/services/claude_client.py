"""Compatibility layer for code that imported the former Claude client."""

from app.services.openai_client import (
    IMAGE_MEDIA_TYPES,
    SUPPORTED_FILE_SUFFIXES,
    OpenAIConfigurationError,
    OpenAIError,
    OpenAIFileError,
    create_response,
    file_content_block,
    get_client,
    is_configured,
    ping,
    validate_supported_file,
)

ClaudeConfigurationError = OpenAIConfigurationError
ClaudeError = OpenAIError
ClaudeFileError = OpenAIFileError
create_message = create_response

__all__ = [
    "IMAGE_MEDIA_TYPES",
    "SUPPORTED_FILE_SUFFIXES",
    "ClaudeConfigurationError",
    "ClaudeError",
    "ClaudeFileError",
    "create_message",
    "file_content_block",
    "get_client",
    "is_configured",
    "ping",
    "validate_supported_file",
]
