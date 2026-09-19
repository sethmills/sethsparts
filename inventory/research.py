"""Web research for enrichment — search the web, then let DeepSeek read the results.

DeepSeek's chat API has no browsing of its own (the Responses API ignores `web_search`),
so the app does the browsing: Tavily searches the web (returning title/url/content per
result), and DeepSeek reads those results and extracts structured facts — product page,
datasheet, pinout, price. This replaces the old export-to-Claude loop with an in-app,
cost-controlled, user-initiated pass.

Opt-in like everything else: an empty TAVILY_API_KEY means research is off and the
queue's in-app enrichment falls back to descriptive-only suggestions.
"""
import json

import requests
from django.conf import settings

from .enrichment_ai import DEEPSEEK_URL, _extract_json

TAVILY_URL = "https://api.tavily.com/search"

FIELDS = (
    "matched_product_name",
    "category",
    "description",
    "manufacturer",
    "product_url",
    "datasheet_url",
    "pinout_url",
    "price",
    "image_url",
    "confidence",
)


def _tavily_key() -> str:
    from .site_config import ai_api_key

    return ai_api_key(settings.TAVILY_API_KEY, "tavily_api_key")


def _deepseek_key() -> str:
    from .site_config import ai_api_key

    return ai_api_key(settings.DEEPSEEK_API_KEY, "deepseek_api_key")


def is_configured() -> bool:
    return bool(_tavily_key() and _deepseek_key())


def search_part(name: str):
    """Search the web for a part. Returns (list of {title, url, content}, error)."""
    api_key = _tavily_key()
    if not api_key:
        return [], "Tavily isn't configured — set TAVILY_API_KEY."
    try:
        resp = requests.post(
            TAVILY_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "query": f'"{name}" product page OR datasheet OR pinout',
                "search_depth": "basic",
                "max_results": 4,
                "include_answer": True,
            },
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        return [], f"Search failed: {exc}"
    except ValueError:
        return [], "Search returned something that wasn't JSON."

    results = [
        {"title": r.get("title") or "", "url": r.get("url") or "", "content": r.get("content") or ""}
        for r in payload.get("results", [])
    ]
    return results, None


def extract_part_data(name: str, results, context: str = ""):
    """DeepSeek reads the search results and extracts structured facts."""
    api_key = _deepseek_key()
    if not api_key:
        return {}, "DeepSeek isn't configured — set DEEPSEEK_API_KEY."
    if not results:
        return {}, "No search results to read."

    results_text = "\n\n".join(
        f"[{i}] {r['title']}\n{r['url']}\n{r['content'][:2000]}"
        for i, r in enumerate(results, start=1)
    )
    prompt = (
        "Given this part name and the search results, identify the part and extract what you can.\n"
        "Reply with a JSON object and nothing else, using these keys:\n"
        '{"matched_product_name": "", "category": "", "description": "", "manufacturer": "", '
        '"product_url": "", "datasheet_url": "", "pinout_url": "", "price": "", "image_url": "", '
        '"confidence": "high"}\n'
        "Use empty strings when unsure. Only use URLs that actually appear in the results. "
        'Set "confidence" to "low" if the match is uncertain or the part is generic.\n'
        f"Part name: {name}{context}\n\nSearch results:\n{results_text}"
    )
    try:
        resp = requests.post(
            DEEPSEEK_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": settings.DEEPSEEK_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            },
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(_extract_json(content))
    except requests.RequestException as exc:
        return {}, f"DeepSeek request failed: {exc}"
    except (KeyError, ValueError, TypeError) as exc:
        return {}, f"DeepSeek returned an unexpected response: {exc}"

    data = {field: str(parsed.get(field) or "").strip() for field in FIELDS}
    data["confidence"] = "low" if data.get("confidence") != "high" else "high"
    return data, None


def research_part(name, category=None, description=None, manufacturer=None):
    """Search the web for a part and extract structured facts. Returns (dict, error)."""
    if not is_configured():
        return {}, "Web research isn't configured — set TAVILY_API_KEY and DEEPSEEK_API_KEY."

    context = ""
    if category:
        context += f"\nCurrent category: {category}"
    if description:
        context += f"\nCurrent description: {description}"
    if manufacturer:
        context += f"\nCurrent manufacturer: {manufacturer}"

    results, error = search_part(name)
    if error:
        return {}, error
    return extract_part_data(name, results, context)
