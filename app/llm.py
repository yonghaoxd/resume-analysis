"""DeepSeek client (OpenAI-compatible chat completions, JSON output)."""
import json
import os

import httpx


class LLMError(Exception):
    pass


def chat_json(system: str, user: str) -> dict:
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise LLMError(
            "DeepSeek API key is missing. Put it in the .env file as DEEPSEEK_API_KEY=... and restart."
        )
    base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "max_tokens": 8000,
        "response_format": {"type": "json_object"},
    }

    last_error = "unknown error"
    for _ in range(2):  # JSON mode occasionally returns empty or cut-off content
        try:
            resp = httpx.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
                timeout=180,
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"Could not reach DeepSeek: {exc}")
        if resp.status_code == 401:
            raise LLMError("DeepSeek rejected the API key. Check DEEPSEEK_API_KEY in .env.")
        if resp.status_code == 402:
            raise LLMError("DeepSeek account has insufficient balance.")
        if resp.status_code >= 400:
            raise LLMError(f"DeepSeek error {resp.status_code}: {resp.text[:300]}")
        try:
            content = resp.json()["choices"][0]["message"]["content"] or ""
            data = json.loads(content)
            if isinstance(data, dict):
                return data
            last_error = "response was not a JSON object"
        except (KeyError, IndexError, ValueError) as exc:
            last_error = str(exc)
    raise LLMError(f"DeepSeek returned an unusable answer ({last_error}). Try again.")
