import json
import sys
from typing import Any

import requests

# Fill these before running
BASE_URL = "https://804e8fa8-a965-4239-a05b-d272a9a45f2e.web.createdevserver.com/api"
API_KEY = "sk-proj-JwQknAJy2BPfDrLkLGYHfjxmxtLWcBgufnnzxNSoR4sNvOV1"
MODEL = "claude-opus-4.6"
TIMEOUT = 30


def normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def request_json(method: str, url: str, **kwargs: Any) -> requests.Response:
    response = requests.request(method=method, url=url, timeout=TIMEOUT, **kwargs)
    return response


def print_response(title: str, response: requests.Response) -> None:
    print(f"\n=== {title} ===")
    print(f"status: {response.status_code}")
    print("headers:")
    for key, value in response.headers.items():
        print(f"  {key}: {value}")
    print("body:")
    try:
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    except ValueError:
        print(response.text)


def main() -> int:
    base_url = normalize_base_url(BASE_URL)
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    if "your-openai-compatible-base-url" in base_url or API_KEY == "sk-...":
        print("Please fill BASE_URL and API_KEY first.")
        return 1

    try:
        models_response = request_json("GET", f"{base_url}/v1/models", headers=headers)
        print_response("GET /v1/models", models_response)

        chat_payload = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "You are a concise test assistant."},
                {"role": "user", "content": "Reply with exactly: ok"},
            ],
            "temperature": 0,
        }
        chat_response = request_json(
            "POST",
            f"{base_url}/v1/chat/completions",
            headers=headers,
            json=chat_payload,
        )
        print_response("POST /v1/chat/completions", chat_response)
        return 0
    except requests.RequestException as exc:
        print(f"Request failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
