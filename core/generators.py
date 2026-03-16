"""Blog generators using Google Gemini models."""

import concurrent.futures
import logging
import os
import time
from typing import List

import yaml
from google import genai
from google.genai import types

from core.models import DocSet

logger = logging.getLogger(__name__)

# Prompt config cache
_PROMPT_CONFIGS = {}


def _load_prompt_config(input_format: str = "pdf") -> dict:
    """Load prompt config for the given input format ('pdf' or 'text')."""
    if input_format in _PROMPT_CONFIGS:
        return _PROMPT_CONFIGS[input_format]

    if input_format == "pdf":
        config_file = "pdf_prompts.yaml"
    elif input_format == "text":
        config_file = "text_prompts.yaml"
    else:
        raise ValueError(f"Unsupported input format: {input_format}")

    config_path = os.path.join(os.path.dirname(__file__), "prompts", config_file)
    with open(config_path, "r", encoding="utf-8") as f:
        _PROMPT_CONFIGS[input_format] = yaml.safe_load(f)

    return _PROMPT_CONFIGS[input_format]


def format_blog_prompt(
    data_path: str,
    arxiv_id: str,
    text_chunks: str,
    table_chunks: str,
    figure_chunks: str,
    title: str,
    input_format: str = "pdf",
) -> str:
    """Format the blog generation prompt."""
    config = _load_prompt_config(input_format)

    if input_format == "pdf":
        return config["blog_generation_prompt"].format(
            data_path=data_path,
            arxiv_id=arxiv_id,
            figure_chunks=figure_chunks,
            title=title,
        )
    else:
        return config["blog_generation_prompt"].format(
            data_path=data_path,
            arxiv_id=arxiv_id,
            text_chunks=text_chunks,
            table_chunks=table_chunks,
            figure_chunks=figure_chunks,
            title=title,
        )


class GeminiBlogGenerator_default:
    """Generate blog posts for all papers using Gemini (batch/default mode)."""

    def __init__(
        self,
        model_name="gemini-2.5-flash-lite-preview-09-2025",
        data_path="./output",
        output_path="./experiments/output",
        input_format="pdf",
        max_tokens=8192,
        temperature=0.7,
        api_key=None,
        rate_limiter=None,
        token_tracker=None,
        username="BlogBot@gmail.com",
    ):
        if api_key is None:
            api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set")
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self.data_path = data_path
        self.output_path = output_path
        self.input_format = input_format
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.rate_limiter = rate_limiter
        self.token_tracker = token_tracker
        self.username = username

    def generate_digest(self, papers: List[DocSet], input_format="pdf"):
        def generate_with_delay(paper):
            self._generate_single_blog(paper, input_format)
            time.sleep(5)

        max_workers = min(len(papers), 50)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(generate_with_delay, paper) for paper in papers]
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error("Error processing paper: %s", e)

    def _generate_single_blog(self, paper: DocSet, input_format="pdf"):
        pdf_data = None
        if input_format == "pdf":
            with open(paper.pdf_path, "rb") as pdf_file:
                pdf_data = pdf_file.read()

        arxiv_id = paper.doc_id
        prompt = format_blog_prompt(
            data_path=self.data_path,
            arxiv_id=arxiv_id,
            text_chunks=paper.text_chunks,
            table_chunks=paper.table_chunks,
            figure_chunks=paper.figure_chunks,
            title=paper.title,
            input_format=input_format,
        )

        max_retries = 5
        response = None
        for attempt in range(1, max_retries + 1):
            try:
                if self.rate_limiter:
                    try:
                        self.rate_limiter.acquire()
                    except Exception as e:
                        logger.warning("Rate limit error for %s: %s", arxiv_id, e)
                        if attempt < max_retries:
                            time.sleep(60)
                            continue
                        else:
                            return

                contents = [prompt]
                if input_format == "pdf" and pdf_data:
                    contents.append(
                        types.Part.from_bytes(data=pdf_data, mime_type="application/pdf")
                    )

                response = self.client.models.generate_content(
                    model=self.model_name, contents=contents
                )

                if self.token_tracker and hasattr(response, "usage_metadata"):
                    prompt_tokens = response.usage_metadata.prompt_token_count
                    response_tokens = response.usage_metadata.candidates_token_count
                    self.token_tracker.track(
                        username=self.username,
                        operation="blog_generation",
                        prompt_tokens=prompt_tokens,
                        response_tokens=response_tokens,
                    )
                    logger.info(
                        "[%s] Blog generation for %s - Tokens: prompt=%d, response=%d, total=%d",
                        self.username, arxiv_id, prompt_tokens, response_tokens,
                        prompt_tokens + response_tokens,
                    )

                break
            except Exception as e:
                logger.error("Error (attempt %d): %s", attempt, e)
                if attempt < max_retries:
                    sleep_time = 2 ** attempt
                    logger.info("Retrying in %ds...", sleep_time)
                    time.sleep(sleep_time)
                else:
                    logger.error("Max retries reached for %s", arxiv_id)
                    return

        if response is None:
            return

        markdown_path = os.path.join(self.output_path, f"{arxiv_id}.md")
        os.makedirs(os.path.dirname(markdown_path), exist_ok=True)
        with open(markdown_path, "w", encoding="utf-8") as md_file:
            md_file.write(response.text)
        logger.info("Blog saved: %s", markdown_path)


class GeminiBlogGenerator_recommend:
    """Generate blog posts for recommended papers (per-user mode)."""

    def __init__(
        self,
        model_name="gemini-2.5-flash-preview-09-2025",
        data_path="./output",
        output_path="./experiments/output",
        input_format="pdf",
        max_tokens=4096,
        temperature=0.5,
        api_key=None,
        rate_limiter=None,
        token_tracker=None,
        username="default",
    ):
        if api_key is None:
            api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set")
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self.data_path = data_path
        self.output_path = output_path
        self.input_format = input_format
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.rate_limiter = rate_limiter
        self.token_tracker = token_tracker
        self.username = username

    def generate_digest(self, papers: List[DocSet], input_format="pdf"):
        def generate_with_delay(paper):
            self._generate_single_blog(paper, input_format)
            time.sleep(5)

        max_workers = min(len(papers), 50)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            paper_to_future = {
                i: (paper, executor.submit(generate_with_delay, paper))
                for i, paper in enumerate(papers)
            }
            for i in range(len(papers)):
                paper, future = paper_to_future[i]
                try:
                    future.result()
                except Exception as e:
                    logger.error("Error processing paper %s: %s", paper.doc_id, e)

    def _generate_single_blog(self, paper: DocSet, input_format="pdf"):
        logger.info("Generating blog for %s: %s", paper.doc_id, paper.title[:100])

        pdf_data = None
        if input_format == "pdf":
            with open(paper.pdf_path, "rb") as pdf_file:
                pdf_data = pdf_file.read()

        arxiv_id = paper.doc_id
        prompt = format_blog_prompt(
            data_path=self.data_path,
            arxiv_id=arxiv_id,
            text_chunks=str(paper.text_chunks),
            table_chunks=str(paper.table_chunks),
            figure_chunks=str(paper.figure_chunks),
            title=paper.title,
            input_format=input_format,
        )

        max_retries = 5
        response = None
        for attempt in range(1, max_retries + 1):
            try:
                if self.rate_limiter:
                    try:
                        self.rate_limiter.acquire()
                    except Exception as e:
                        logger.warning("Rate limit error for %s: %s", arxiv_id, e)
                        if attempt < max_retries:
                            time.sleep(60)
                            continue
                        else:
                            return

                contents = [prompt]
                if input_format == "pdf" and pdf_data:
                    contents.append(
                        types.Part.from_bytes(data=pdf_data, mime_type="application/pdf")
                    )

                response = self.client.models.generate_content(
                    model=self.model_name, contents=contents
                )

                if self.token_tracker and hasattr(response, "usage_metadata"):
                    prompt_tokens = response.usage_metadata.prompt_token_count
                    response_tokens = response.usage_metadata.candidates_token_count
                    self.token_tracker.track(
                        username=self.username,
                        operation="recommendation",
                        prompt_tokens=prompt_tokens,
                        response_tokens=response_tokens,
                    )
                    logger.info(
                        "[%s] Recommendation for %s - Tokens: prompt=%d, response=%d, total=%d",
                        self.username, arxiv_id, prompt_tokens, response_tokens,
                        prompt_tokens + response_tokens,
                    )

                break
            except Exception as e:
                logger.error("Error (attempt %d): %s", attempt, e)
                if attempt < max_retries:
                    sleep_time = 2 ** attempt
                    logger.info("Retrying in %ds...", sleep_time)
                    time.sleep(sleep_time)
                else:
                    logger.error("Max retries reached for %s", arxiv_id)
                    return

        if response is None:
            return

        markdown_path = os.path.join(self.output_path, f"{arxiv_id}.md")
        os.makedirs(os.path.dirname(markdown_path), exist_ok=True)
        with open(markdown_path, "w", encoding="utf-8") as md_file:
            md_file.write(response.text)
        logger.info("Blog saved: %s", markdown_path)
