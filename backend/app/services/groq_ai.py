"""Groq REST client with key rotation for chat JSON planning."""
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


async def generate_json(prompt: str, *, timeout: int = 45):
    """Try configured Groq keys one by one and return parsed JSON or None."""
    global _key_offset

    settings = get_settings()
    keys = settings.groq_api_keys
    if not keys:
        return None

    ordered = keys[_key_offset:] + keys[:_key_offset]
    body = {
        "model": settings.groq_chat_model,
        "temperature": 0.25,
        "messages": [
            {
                "role": "system",
                "content": "Return strict JSON only. No markdown. No prose.",
            },
            {"role": "user", "content": prompt},
        ],
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        for idx, key in enumerate(ordered):
            try:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json=body,
                )
                if resp.status_code in {401, 403, 408, 413, 429, 500, 502, 503, 504}:
                    continue
                resp.raise_for_status()
                content = (
                    resp.json()
                    .get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                parsed = _strip_json(content)
                _key_offset = (keys.index(key) + 1) % len(keys)
                return parsed
            except Exception:
                if idx == len(ordered) - 1:
                    return None
                continue
    return None
