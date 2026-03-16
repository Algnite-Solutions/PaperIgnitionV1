import os
import json
import yaml
import asyncio
from typing import Optional, Dict, Any

from core.generators import GeminiBlogGenerator_default, GeminiBlogGenerator_recommend
from core.models import DocSet

try:
    from .rate_limiter import RateLimiter, RateLimitError
except ImportError:
    from rate_limiter import RateLimiter, RateLimitError


def run_Gemini_blog_generation_default(
    papers,
    output_path="./blogByGemini",
    model_config: Optional[Dict[str, Any]] = None,
    rate_limiter: Optional[RateLimiter] = None,
    token_tracker=None,
    username="BlogBot@gmail.com"
):
    if model_config is None:
        model_config = {
            "model_id": "gemini-2.5-flash-lite-preview-09-2025",
            "api_key_env": "GEMINI_API_KEY",
            "max_tokens": 8192,
            "temperature": 0.7
        }

    api_key = os.getenv(model_config.get("api_key_env", "GEMINI_API_KEY"))

    generator = GeminiBlogGenerator_default(
        model_name=model_config.get("model_id", "gemini-2.5-flash-lite-preview-09-2025"),
        data_path="./imgs/",
        output_path=output_path,
        max_tokens=model_config.get("max_tokens", 8192),
        temperature=model_config.get("temperature", 0.7),
        api_key=api_key,
        rate_limiter=rate_limiter,
        token_tracker=token_tracker,
        username=username
    )
    generator.generate_digest(papers)


def run_Gemini_blog_generation_recommend(
    papers,
    output_path="./blogByGemini",
    model_config: Optional[Dict[str, Any]] = None,
    rate_limiter: Optional[RateLimiter] = None,
    token_tracker=None,
    username="default"
):
    if model_config is None:
        model_config = {
            "model_id": "gemini-2.5-flash-preview-09-2025",
            "api_key_env": "GEMINI_API_KEY",
            "max_tokens": 4096,
            "temperature": 0.5
        }

    api_key = os.getenv(model_config.get("api_key_env", "GEMINI_API_KEY"))

    generator = GeminiBlogGenerator_recommend(
        model_name=model_config.get("model_id", "gemini-2.5-flash-preview-09-2025"),
        data_path="./imgs/",
        output_path=output_path,
        max_tokens=model_config.get("max_tokens", 4096),
        temperature=model_config.get("temperature", 0.5),
        api_key=api_key,
        rate_limiter=rate_limiter,
        token_tracker=token_tracker,
        username=username
    )
    generator.generate_digest(papers)
