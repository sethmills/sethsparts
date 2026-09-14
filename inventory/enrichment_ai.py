"""LLM-assisted enrichment — suggest category/description/manufacturer via DeepSeek.

Opt-in and approve-before-save: nothing is written until the owner confirms a
suggestion. The app reads its own DEEPSEEK_API_KEY (each installer supplies their
own, the same way they supply SMTP/Gmail credentials), so enrichment is simply
off — the button hidden — until configured.
"""

import json
import re

import requests
from django.conf import settings

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

_SYSTEM_PROMPT = (
    "You tidy a home workshop inventory. Given a part name and whatever is already "
    "known, suggest a concise category (2-4 words), a one-line description, and a "
    "manufacturer only if you're confident. Reply with a JSON object and nothing "
    'else: {"category": "...", "description": "...", "manufacturer": "..."}. '
    "Use empty strings when unsure. Never invent a model number not in the name."
)


def _extract_json(text):
    """Pull the first JSON object out of a model reply, tolerating markdown fences
    or surrounding prose — the chat model is asked for JSON but isn't always terse."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    return text[start:end + 1]


def is_configured():
    return bool(settings.DEEPSEEK_API_KEY)


def suggest_enrichment(name, category=None, description=None, manufacturer=None):
    """Return (suggestion_dict, None) on success or (None, error_message)."""
    api_key = settings.DEEPSEEK_API_KEY
    if not api_key:
        return None, "DeepSeek isn't configured — set DEEPSEEK_API_KEY."

    user_text = f"Part name: {name}"
    if category:
        user_text += f"\nCurrent category: {category}"
    if description:
        user_text += f"\nCurrent description: {description}"
    if manufacturer:
        user_text += f"\nCurrent manufacturer: {manufacturer}"

    try:
        resp = requests.post(
            DEEPSEEK_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": settings.DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_text},
                ],
                "temperature": 0,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(_extract_json(content))
        return {
            "category": (parsed.get("category") or "").strip(),
            "description": (parsed.get("description") or "").strip(),
            "manufacturer": (parsed.get("manufacturer") or "").strip(),
        }, None
    except requests.RequestException as exc:
        return None, f"DeepSeek request failed: {exc}"
    except (KeyError, ValueError, TypeError) as exc:
        return None, f"DeepSeek returned an unexpected response: {exc}"
