"""Test OpenAI authentication without printing the API key."""

import json

from app.services.openai_client import OpenAIError, ping


def main() -> int:
    try:
        result = ping()
    except OpenAIError as exc:
        print(json.dumps({"status": "error", "detail": str(exc)}))
        return 1

    print(
        json.dumps(
            {
                "status": "connected",
                "model": result["model"],
                "request_id": result["request_id"],
                "response": result["text"],
                "usage": result["usage"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
