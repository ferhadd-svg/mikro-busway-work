"""Verify deployed Render health and OpenAI authentication endpoints."""

import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_json(url: str, method: str = "GET") -> dict:
    request = Request(url, method=method, headers={"Accept": "application/json"})
    with urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://work-16.onrender.com")
    parser.add_argument("--test-claude", action="store_true")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    try:
        print(json.dumps(request_json(f"{base_url}/health"), indent=2))
        print(json.dumps(request_json(f"{base_url}/ai/status"), indent=2))
        if args.test_claude:
            print(
                json.dumps(
                    request_json(f"{base_url}/ai/test-connection", "POST"),
                    indent=2,
                )
            )
    except (HTTPError, URLError, TimeoutError) as exc:
        print(json.dumps({"status": "error", "detail": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
