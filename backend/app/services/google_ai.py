"""Small Gemini REST client with key rotation for optional planning tasks."""
import json
import re

import httpx

from app.config import get_settings

_key_offset = 0


def _strip_json(text: str):
    clean = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", clean, flags=re.S | re.I)
    if fenced:
        clean = fenced.group(1).strip()
    return json.loads(clean)


def _candidate_text(payload: dict) -> str:
    parts = (
        payload.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [])
    )
    return "\n".join(str(part.get("text", "")) for part in parts if part.get("text")).strip()


async def generate_json(prompt: str, *, timeout: int = 30):
    """Try configured Gemini keys one by one and return parsed JSON or None."""
    global _key_offset

    settings = get_settings()
    keys = settings.google_ai_api_keys
    if not keys:
        return None

    ordered = keys[_key_offset:] + keys[:_key_offset]
    body = {
        "contents": [{
            "parts": [{"text": prompt}],
        }],
        "generationConfig": {
            "temperature": 0.45,
            "responseMimeType": "application/json",
        },
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        for idx, key in enumerate(ordered):
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{settings.google_ai_model}:generateContent"
            )
            try:
                resp = await client.post(url, params={"key": key}, json=body)
                if resp.status_code in {401, 403, 429, 500, 502, 503, 504}:
                    continue
                resp.raise_for_status()
                parsed = _strip_json(_candidate_text(resp.json()))
                _key_offset = (keys.index(key) + 1) % len(keys)
                return parsed
            except Exception:
                if idx == len(ordered) - 1:
                    return None
                continue
    return None
