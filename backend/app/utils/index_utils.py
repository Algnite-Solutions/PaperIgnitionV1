import logging
import os

import requests

logger = logging.getLogger(__name__)


def search_papers_via_api(api_url, query, search_strategy='tf-idf', similarity_cutoff=0.1, filters=None):
    """Search papers using the /find_similar/ endpoint for a single query.
    Returns a list of paper dictionaries corresponding to the results.
    """
    payload = {
        "query": query,
        "top_k": 3,
        "similarity_cutoff": similarity_cutoff,
        "search_strategies": [(search_strategy, 0.5)],
        "filters": filters,
        "result_include_types": ["metadata", "text_chunks"]
    }
    try:
        response = requests.post(f"{api_url}/find_similar/", json=payload, timeout=30.0)
        response.raise_for_status()
        results = response.json()
        logger.info(f"Search results: {len(results)} for query '{query}'")
        return results
    except Exception as e:
        logger.error(f"Search failed for '{query}': {e}")
        return []


_TRANSLATE_PROMPT = """You are an expert bilingual rewriter specializing in English and Chinese.
Your job is to produce a clear, information-rich English query for semantic search or dense retrieval.

When given an input in either Chinese or English:
- If it's in Chinese, translate it into fluent, natural English.
- If it's already in English, keep it in English.
- In both cases, rewrite or expand it slightly to make the user's intent explicit and unambiguous.
- Focus on preserving the meaning, not literal translation.
- Do NOT add explanations, metadata, or prefixes like "Translation:".
- Output only the final English text.
"""


def translate_text_gemini(text: str, api_key: str | None = None) -> str | None:
    """Translate/rewrite research interests to English using Gemini."""
    from google import genai

    if api_key is None:
        api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not set, cannot translate")
        return None

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=f"{_TRANSLATE_PROMPT}\n\nUser input:\n{text}",
        )
        return response.text.strip() if response.text else None
    except Exception as e:
        logger.error(f"Gemini translation failed: {e}")
        return None
