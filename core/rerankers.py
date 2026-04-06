"""LLM-based rerankers using Google Gemini models."""

from __future__ import annotations

import io
import logging
import os
import re
from pathlib import Path

import yaml
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


def extract_first_page_pdf(pdf_path: str | Path) -> bytes | None:
    """Extract the first page from a PDF file and return it as bytes."""
    try:
        import PyPDF2
    except ImportError:
        logger.warning("PyPDF2 not installed, cannot extract first page")
        return None

    try:
        with open(pdf_path, "rb") as file:
            reader = PyPDF2.PdfReader(file)
            if len(reader.pages) == 0:
                return None

            writer = PyPDF2.PdfWriter()
            writer.add_page(reader.pages[0])

            output = io.BytesIO()
            writer.write(output)
            output.seek(0)
            return output.read()
    except Exception as e:
        logger.warning("Failed to extract first page from %s: %s", pdf_path, e)
        return None


class GeminiReranker:
    """Rerank retrieved documents using Gemini with text input."""

    def __init__(self, model_name="gemini-2.5-pro", prompt_key="blog_rerank_prompt"):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set")
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name

        prompt_path = Path(__file__).parent / "prompts" / "rerank_prompts.yaml"
        with open(prompt_path, "r") as f:
            prompts = yaml.safe_load(f)
            self.rerank_prompt_template = prompts[prompt_key]

    def rerank(self, query, corpus_dict, retrieve_ids, top_k=5):
        """Rerank documents based on query relevance.

        Args:
            query: Research question
            corpus_dict: Dict mapping doc IDs to content text
            retrieve_ids: List of doc IDs to rerank
            top_k: Number of top documents to return

        Returns:
            List of top_k reranked document IDs
        """
        documents_text = ""
        for doc_id in retrieve_ids:
            if doc_id in corpus_dict:
                documents_text += f"Document ID: {doc_id}\n{corpus_dict[doc_id]}\n\n"

        prompt = self.rerank_prompt_template.format(
            documents_text=documents_text, query=query
        )

        response = self.client.models.generate_content(
            model=self.model_name, contents=prompt
        )

        doc_ids = self._parse_document_ids(response.text)
        return doc_ids[:top_k]

    def _parse_document_ids(self, response_text: str) -> list[str]:
        match = re.search(r"<Documents>(.*?)</Documents>", response_text, re.DOTALL)
        if match:
            return [line.strip() for line in match.group(1).strip().split("\n") if line.strip()]
        return []


class GeminiRerankerPDF:
    """Rerank documents using Gemini with PDF first-page support."""

    def __init__(
        self,
        prompt_path=None,
        model_name="gemini-2.5-pro",
        prompt_key="blog_rerank_pdf_prompt",
        enable_thinking=True,
    ):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set")
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self.enable_thinking = enable_thinking

        if not prompt_path:
            prompt_path = Path(__file__).parent / "prompts" / "rerank_prompts.yaml"
        self.prompt_key = prompt_key
        with open(prompt_path, "r") as f:
            prompts = yaml.safe_load(f)
            self.rerank_prompt_template = prompts[prompt_key]
            self.personalized_prompt_template = prompts.get("personalized_ranking_prompt")

    def rerank(self, query, pdf_paths_dict, retrieve_ids, top_k=5, user_profile=None):
        """Rerank documents using PDF first pages.

        Returns:
            Tuple of (reranked_doc_ids, thought_summary)
        """
        contents = []
        documents_text_parts = []

        for doc_id in retrieve_ids:
            if doc_id not in pdf_paths_dict:
                continue

            pdf_path = pdf_paths_dict[doc_id]
            try:
                first_page_pdf = extract_first_page_pdf(pdf_path)
                if first_page_pdf is None:
                    logger.warning("Could not extract first page from %s", pdf_path)
                    continue

                documents_text_parts.append(f"\n=== Document ID: {doc_id} ===\n")
                documents_text_parts.append(
                    types.Part.from_bytes(data=first_page_pdf, mime_type="application/pdf")
                )
            except Exception as e:
                logger.warning("Failed to process PDF %s: %s", pdf_path, e)

        contents.extend(documents_text_parts)

        if user_profile is not None and self.personalized_prompt_template:
            neg_constraints = user_profile.get("negative_constraints", [])
            heuristics = user_profile.get("ranking_heuristics", [])
            neg_str = "\n".join(f"- {c}" for c in neg_constraints) if neg_constraints else "None"
            heur_str = "\n".join(f"- {h}" for h in heuristics) if heuristics else "None"
            query_str = query if isinstance(query, str) else query.get("user_interest_description", "")

            prompt = self.personalized_prompt_template.format(
                documents_text="[PDFs are provided above with Document IDs]",
                persona_definition=user_profile.get("persona_definition", ""),
                negative_constraints=neg_str,
                ranking_heuristics=heur_str,
                user_interest_description=query_str,
            )
        else:
            prompt = self.rerank_prompt_template.format(
                documents_text="[PDFs are provided above with Document IDs]",
                user_interest_description=query if isinstance(query, str) else str(query),
            )

        contents.append(prompt)

        try:
            config_params = {}
            if self.enable_thinking:
                config_params["thinking_config"] = types.ThinkingConfig(include_thoughts=True)

            response = self.client.models.generate_content(
                model=self.model_name,
                config=types.GenerateContentConfig(**config_params) if config_params else None,
                contents=contents,
            )

            thought_summary = ""
            if self.enable_thinking:
                if hasattr(response, "candidates") and len(response.candidates) > 0:
                    candidate = response.candidates[0]
                    if hasattr(candidate, "content") and hasattr(candidate.content, "parts"):
                        for part in candidate.content.parts:
                            if hasattr(part, "thought") and part.thought:
                                thought_summary = part.text
                                logger.info("Thought summary captured (%d chars)", len(thought_summary))
                                break

            doc_ids = self._parse_document_ids(response.text)
            return doc_ids[:top_k], thought_summary

        except Exception as e:
            logger.error("Error during reranking: %s", e)
            return retrieve_ids[:top_k], ""

    def _parse_document_ids(self, response_text: str) -> list[str]:
        match = re.search(r"<Documents>(.*?)</Documents>", response_text, re.DOTALL)
        if match:
            return [line.strip() for line in match.group(1).strip().split("\n") if line.strip()]
        return []


class GeminiProfileExtractor:
    """Extract a user's research profile from their liked/unliked paper history using PDF first pages.

    Mirrors the Verbalizer class from the AIgnite experiment — same PDF-first-page approach,
    same profile_extraction_prompt, same output structure (persona_definition, negative_constraints,
    ranking_heuristics).
    """

    def __init__(self, model_name: str = "gemini-2.5-flash", prompt_key: str = "profile_extraction_prompt"):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set")
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name

        prompt_path = Path(__file__).parent / "prompts" / "rerank_prompts.yaml"
        with open(prompt_path, "r") as f:
            prompts = yaml.safe_load(f)
            self.prompt_template = prompts[prompt_key]

    def extract_profile(
        self,
        training_data: list[dict],
        pdf_paths_dict: dict[str, str],
        max_papers: int = 50,
    ) -> tuple[dict, dict]:
        """Extract user research profile from training data with PDF first pages.

        Args:
            training_data: List of session dicts, each with:
                - 'day': date string (YYYY-MM-DD)
                - 'candidates': list of {paper_id, label (1=liked/0=not), title, abstract}
            pdf_paths_dict: Mapping of paper_id → local PDF file path
            max_papers: Maximum number of PDF pages to include in the prompt

        Returns:
            Tuple of (profile_dict, usage_dict).
            profile_dict has keys: persona_definition, negative_constraints, ranking_heuristics
        """
        contents = self._build_pdf_contents(training_data, pdf_paths_dict, max_papers)

        prompt = self.prompt_template.format(
            training_examples="[PDF papers are provided above with their IDs and labels]"
        )
        contents.append(prompt)

        logger.info("Extracting profile from %d training sessions with %s", len(training_data), self.model_name)

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
            )
            profile = self._parse_json_response(response.text)

            usage: dict = {"input_tokens": 0, "thoughts_tokens": 0, "total_tokens": 0}
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                usage["input_tokens"] = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
                usage["thoughts_tokens"] = getattr(response.usage_metadata, "thoughts_token_count", 0) or 0
                usage["total_tokens"] = getattr(response.usage_metadata, "total_token_count", 0) or 0

            logger.info("Profile extracted successfully (tokens: %d)", usage["total_tokens"])
            return profile, usage

        except Exception as e:
            logger.error("Profile extraction failed: %s", e)
            return self._default_profile(), {"input_tokens": 0, "thoughts_tokens": 0, "total_tokens": 0}

    def _build_pdf_contents(
        self,
        training_data: list[dict],
        pdf_paths_dict: dict[str, str],
        max_papers: int,
    ) -> list:
        contents: list = []
        paper_count = 0

        for day_data in training_data:
            if paper_count >= max_papers:
                break

            day_str = day_data.get("day", "Unknown")
            contents.append(f"\n=== Day: {day_str} ===")

            candidates = day_data.get("candidates", [])
            positives = [c for c in candidates if c.get("label") == 1]
            negatives = [c for c in candidates if c.get("label") == 0]

            if positives:
                contents.append("--- LIKED Papers (User gave positive feedback) ---")
                for pos in positives:
                    if paper_count >= max_papers:
                        break
                    paper_id = pos.get("paper_id", "")
                    if paper_id not in pdf_paths_dict:
                        continue
                    first_page = extract_first_page_pdf(pdf_paths_dict[paper_id])
                    if first_page is None:
                        continue
                    contents.append(f"\n[Paper ID: {paper_id}] - LIKED")
                    contents.append(types.Part.from_bytes(data=first_page, mime_type="application/pdf"))
                    paper_count += 1

            if negatives and paper_count < max_papers:
                contents.append("\n--- SHOWN but NOT LIKED Papers ---")
                for neg in negatives:
                    if paper_count >= max_papers:
                        break
                    paper_id = neg.get("paper_id", "")
                    if paper_id not in pdf_paths_dict:
                        continue
                    first_page = extract_first_page_pdf(pdf_paths_dict[paper_id])
                    if first_page is None:
                        continue
                    contents.append(f"\n[Paper ID: {paper_id}] - NOT LIKED")
                    contents.append(types.Part.from_bytes(data=first_page, mime_type="application/pdf"))
                    paper_count += 1

        logger.info("Built profile extraction contents with %d PDF pages", paper_count)
        return contents

    def _parse_json_response(self, response_text: str) -> dict:
        if "```json" in response_text:
            start = response_text.find("```json") + 7
            end = response_text.find("```", start)
            json_str = response_text[start:end].strip()
        elif "```" in response_text:
            start = response_text.find("```") + 3
            end = response_text.find("```", start)
            json_str = response_text[start:end].strip()
        else:
            json_str = response_text.strip()

        import json
        return json.loads(json_str)

    def _default_profile(self) -> dict:
        return {
            "persona_definition": "Researcher interested in machine learning and AI",
            "negative_constraints": ["Avoid irrelevant topics"],
            "ranking_heuristics": ["Prioritize recent papers", "Prefer empirical results"],
        }
