"""PDFExtractor: convert PDF to markdown via OCR, then parse into chunks.

Provides a base class and implementations for different OCR backends:
- PDFExtractor_volcengine: Uses VolcEngine (火山引擎) OCR
- PDFExtractor_baidu: Uses Baidu (百度) OCR
"""

from __future__ import annotations

import base64
import logging
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path

from bs4 import BeautifulSoup

from core.arxiv.downloader import compress_pdf
from core.models import ChunkType, FigureChunk, TableChunk, TextChunk

logger = logging.getLogger(__name__)


class PDFExtractorBase(ABC):
    """Abstract base class for PDF extraction via OCR.

    Subclasses must implement the _pdf_to_markdown() method to convert
    PDF to markdown using their specific OCR backend.
    """

    def __init__(self, max_pages: int = 16):
        self.max_pages = max_pages

    def extract(
        self,
        pdf_path: Path | str,
        doc_id: str,
        image_dir: Path | str,
    ) -> tuple[list[TextChunk], list[FigureChunk], list[TableChunk]]:
        """Convert PDF to markdown via OCR, then parse into chunks.

        Args:
            pdf_path: Path to the PDF file
            doc_id: Paper identifier
            image_dir: Directory to save extracted images

        Returns:
            Tuple of (text_chunks, figure_chunks, table_chunks)
        """
        pdf_path = Path(pdf_path)
        image_dir = Path(image_dir)

        markdown = self._pdf_to_markdown(pdf_path)
        if markdown is None:
            logger.warning("OCR failed for %s, returning empty chunks", doc_id)
            return [], [], []

        # Save markdown for debugging
        md_path = pdf_path.parent / f"{doc_id}.md"
        md_path.write_text(markdown, encoding="utf-8")

        text_chunks = self._parse_text(markdown)
        figure_chunks = self._parse_figures(markdown, doc_id, image_dir)
        table_chunks = self._parse_tables(markdown)

        return text_chunks, figure_chunks, table_chunks

    @abstractmethod
    def _pdf_to_markdown(self, pdf_path: Path) -> str | None:
        """Convert PDF to markdown using OCR backend.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            Markdown string, or None if conversion failed
        """
        pass

    def _trim_pdf_pages(self, pdf_path: Path) -> None:
        """Trim PDF to max_pages if it has more pages (in-place modification)."""
        try:
            import fitz

            doc = fitz.open(pdf_path)
            if doc.page_count > self.max_pages:
                logger.info(
                    "PDF has %d pages, trimming to %d: %s",
                    doc.page_count,
                    self.max_pages,
                    pdf_path.name,
                )
                doc.delete_pages(list(range(self.max_pages, doc.page_count)))
                trimmed_path = pdf_path.with_suffix(".trimmed.pdf")
                doc.save(str(trimmed_path), garbage=4, deflate=True)
                doc.close()
                trimmed_path.replace(pdf_path)
            else:
                doc.close()
        except Exception as e:
            logger.warning("Page trimming failed: %s, trying original", e)

    def _compress_pdf_if_needed(self, pdf_path: Path, max_size_mb: float = 4.5) -> None:
        """Compress PDF if it exceeds max_size_mb (in-place modification)."""
        if pdf_path.stat().st_size > max_size_mb * 1024 * 1024:
            logger.info("PDF >%.1fMB, compressing: %s", max_size_mb, pdf_path.name)
            try:
                compress_pdf(pdf_path, max_size_mb=max_size_mb)
            except Exception as e:
                logger.warning("Compression failed: %s, trying original", e)

    def _parse_text(self, markdown: str) -> list[TextChunk]:
        """Parse markdown sections into text chunks."""
        all_text: list[TextChunk] = []

        try:
            # Remove image references
            cleaned = re.sub(r"^!\[fig_[^\n]*\n?", "", markdown, flags=re.MULTILINE)

            # Find top-level headings (## but not subsections like ## 2.1)
            pattern = r"(?:^|\n)(##\s+(?!(?:[A-Za-z]+\.)?\d+\.\d+)[^\n]+)"
            matches = list(re.finditer(pattern, cleaned))

            boundaries = [m.start() for m in matches]
            boundaries.append(len(cleaned))

            for i in range(len(matches)):
                start = boundaries[i]
                end = boundaries[i + 1]
                section_text = cleaned[start:end].strip()
                header_line = matches[i].group(1).strip()
                title = header_line.lstrip("#").strip()

                all_text.append(
                    TextChunk(
                        id=f"text_{i + 1}",
                        type=ChunkType.TEXT,
                        title=title,
                        caption=title,
                        text=section_text,
                    )
                )

        except Exception as e:
            logger.error("Error parsing text: %s", e)

        return all_text

    def _parse_figures(
        self,
        markdown: str,
        doc_id: str,
        image_dir: Path,
    ) -> list[FigureChunk]:
        """Parse figure references from markdown and download images."""
        import requests

        figures: list[FigureChunk] = []
        image_dir.mkdir(parents=True, exist_ok=True)

        # Find all image URLs
        url_pattern = r"!\[.*?\]\((https?://[^\)]+)\)"
        urls = re.findall(url_pattern, markdown)

        for url in urls:
            name = self._extract_figure_name(markdown, url)
            if not name:
                continue
            name = f"{doc_id}_{name}"
            caption = self._extract_caption(markdown, url)

            save_path = image_dir / f"{name}.png"
            try:
                response = requests.get(url, stream=True, timeout=15)
                response.raise_for_status()
                save_path.write_bytes(response.content)
                logger.info("Downloaded figure: %s", name)

                figures.append(
                    FigureChunk(
                        id=None,
                        title=name,
                        type=ChunkType.FIGURE,
                        image_path=str(save_path),
                        alt_text="Refer to caption",
                        caption=caption,
                    )
                )
            except Exception as e:
                logger.error("Failed to download figure %s: %s", url, e)

        return figures

    def _parse_tables(self, markdown: str) -> list[TableChunk]:
        """Parse HTML tables from markdown."""
        tables: list[TableChunk] = []

        try:
            soup = BeautifulSoup(markdown, "html.parser")
            for idx, table in enumerate(soup.find_all("table")):
                table_html = str(table)
                table_pos = markdown.find(table_html)
                context_before = markdown[max(0, table_pos - 500) : table_pos]

                caption_match = re.search(
                    r"(Table\s*\d+[.:]?\s*)([^\n<]+)", context_before, re.IGNORECASE
                )
                if caption_match:
                    table_name = caption_match.group(1).strip().rstrip(":").rstrip(".")
                    caption_text = caption_match.group(2).strip()
                else:
                    table_name = f"table_{idx + 1}"
                    caption_text = ""

                tables.append(
                    TableChunk(
                        id=None,
                        title=table_name,
                        type=ChunkType.TABLE,
                        table_html=table_html,
                        caption=caption_text,
                    )
                )

        except Exception as e:
            logger.error("Error parsing tables: %s", e)

        return tables

    @staticmethod
    def _extract_figure_name(content: str, url: str) -> str:
        """Extract figure name from text near the URL.

        Searches for "Figure X" or "Fig. X" pattern within 300 chars after
        or 200 chars before the URL position.

        Returns:
            Normalized figure name (e.g., "Figure1") or empty string if not found.
        """
        url_pos = content.find(url)
        if url_pos == -1:
            return ""

        url_end = url_pos + len(url)

        # Search in a small window after the URL first
        post = content[url_end : url_end + 300].strip()
        match = re.search(r"(fig(?:ure)?\.?\s*\d+)", post, re.IGNORECASE)
        if match:
            return PDFExtractorBase._normalize_figure_name(match.group(0))

        # Fallback: search before the URL (caption sometimes precedes image)
        pre = content[max(0, url_pos - 200) : url_pos].strip()
        match = re.search(r"(fig(?:ure)?\.?\s*\d+)", pre, re.IGNORECASE)
        if match:
            return PDFExtractorBase._normalize_figure_name(match.group(0))

        return ""

    @staticmethod
    def _extract_figure_name_from_img_ref(content: str, img_ref: str) -> str:
        """Extract figure name from markdown content near an image reference.

        Similar to _extract_figure_name but uses image reference string
        (e.g., 'src="imgs/abc.png"') instead of URL.

        Returns:
            Normalized figure name (e.g., "Figure1") or empty string if not found.
        """
        img_pos = content.find(img_ref)
        if img_pos == -1:
            return ""

        img_end = img_pos + len(img_ref)

        # Search after the image reference (300 chars)
        post = content[img_end : img_end + 300].strip()
        match = re.search(r"(fig(?:ure)?\.?\s*\d+)", post, re.IGNORECASE)
        if match:
            return PDFExtractorBase._normalize_figure_name(match.group(0))

        # Fallback: search before the image reference (200 chars)
        pre = content[max(0, img_pos - 200) : img_pos].strip()
        match = re.search(r"(fig(?:ure)?\.?\s*\d+)", pre, re.IGNORECASE)
        if match:
            return PDFExtractorBase._normalize_figure_name(match.group(0))

        return ""

    @staticmethod
    def _normalize_figure_name(raw_name: str) -> str:
        """Normalize figure name to standard format.

        Examples:
            "fig. 1" -> "Figure1"
            "Fig 2" -> "Figure2"
            "figure3" -> "Figure3"
        """
        name = raw_name.replace(".", "").replace(" ", "")
        name = name[0].upper() + name[1:]
        if name.startswith("Fig") and not name.startswith("Figure"):
            name = "Figure" + name[3:]
        return name

    @staticmethod
    def _extract_caption(content: str, url: str) -> str:
        """Extract caption text near the URL."""
        url_end = content.find(url) + len(url)
        post = content[url_end : url_end + 500].lstrip()
        match = re.search(
            r"(fig(?:ure)?\.?\s*\d+[a-zA-Z]?\.*.*?)\n", post, re.IGNORECASE | re.DOTALL
        )
        return match.group(1).strip() if match else ""


class PDFExtractor_volcengine(PDFExtractorBase):
    """Extract text, figures, and tables from PDF via VolcEngine OCR."""

    def __init__(self, volcengine_ak: str, volcengine_sk: str, max_pages: int = 16):
        super().__init__(max_pages=max_pages)
        self.volcengine_ak = volcengine_ak
        self.volcengine_sk = volcengine_sk

    def _pdf_to_markdown(self, pdf_path: Path) -> str | None:
        """Convert PDF to markdown using VolcEngine OCR."""
        try:
            from volcengine.visual.VisualService import VisualService
        except ImportError:
            logger.error("volcengine package not installed, cannot extract PDF")
            return None

        visual_service = VisualService()
        visual_service.set_ak(self.volcengine_ak)
        visual_service.set_sk(self.volcengine_sk)

        # Trim and compress PDF if needed
        self._trim_pdf_pages(pdf_path)
        self._compress_pdf_if_needed(pdf_path)

        with open(pdf_path, "rb") as f:
            pdf_content = f.read()

        form = {
            "image_base64": base64.b64encode(pdf_content).decode(),
            "image_url": "",
            "version": "v3",
            "page_start": 0,
            "page_num": self.max_pages,
            "table_mode": "html",
            "filter_header": "true",
        }

        # Retry up to 2 times on failure
        max_retries = 2
        for attempt in range(1, max_retries + 1):
            try:
                resp = visual_service.ocr_pdf(form)

                if not isinstance(resp, dict) or "data" not in resp:
                    logger.error("OCR response missing 'data': %s", type(resp))
                    return None

                if resp["data"] is None:
                    logger.error("OCR data is None")
                    return None

                markdown = resp["data"].get("markdown")
                if not markdown:
                    logger.error("OCR returned empty markdown")
                    return None

                return markdown

            except Exception as e:
                logger.error(
                    "OCR request failed (attempt %d/%d): %s", attempt, max_retries, e
                )
                if attempt < max_retries:
                    time.sleep(2)

        return None


class PDFExtractor_baidu(PDFExtractorBase):
    """Extract text, figures, and tables from PDF via Baidu OCR.

    Baidu OCR returns markdown with image references in the format:
    src="imgs/xxx.png" along with a mapping of image paths to download URLs.

    This class stores the OCR response during _pdf_to_markdown() so that
    _parse_figures() can download images from the URLs.
    """

    def __init__(
        self,
        api_url: str,
        api_token: str,
        max_pages: int = 16,
        use_doc_orientation_classify: bool = False,
        use_doc_unwarping: bool = False,
        use_chart_recognition: bool = False,
    ):
        super().__init__(max_pages=max_pages)
        self.api_url = api_url
        self.api_token = api_token
        self.use_doc_orientation_classify = use_doc_orientation_classify
        self.use_doc_unwarping = use_doc_unwarping
        self.use_chart_recognition = use_chart_recognition
        # Store image URL mapping from OCR response for later download
        self._image_url_map: dict[str, str] = {}

    def extract(
        self,
        pdf_path: Path | str,
        doc_id: str,
        image_dir: Path | str,
    ) -> tuple[list[TextChunk], list[FigureChunk], list[TableChunk]]:
        """Convert PDF to markdown via OCR, then parse into chunks.

        Overrides base class to clear image URL map before extraction.

        Args:
            pdf_path: Path to the PDF file
            doc_id: Paper identifier
            image_dir: Directory to save extracted images

        Returns:
            Tuple of (text_chunks, figure_chunks, table_chunks)
        """
        # Clear previous image URL mapping
        self._image_url_map = {}
        return super().extract(pdf_path, doc_id, image_dir)

    def _pdf_to_markdown(self, pdf_path: Path) -> str | None:
        """Convert PDF to markdown using Baidu OCR.

        Also stores image URL mapping for later use in _parse_figures().
        """
        import requests

        # Trim and compress PDF if needed
        self._trim_pdf_pages(pdf_path)
        self._compress_pdf_if_needed(pdf_path)

        # Read and encode PDF
        with open(pdf_path, "rb") as f:
            file_bytes = f.read()
            file_data = base64.b64encode(file_bytes).decode("ascii")

        headers = {
            "Authorization": f"token {self.api_token}",
            "Content-Type": "application/json",
        }

        payload = {
            "file": file_data,
            "fileType": 0,  # PDF documents
            "useDocOrientationClassify": self.use_doc_orientation_classify,
            "useDocUnwarping": self.use_doc_unwarping,
            "useChartRecognition": self.use_chart_recognition,
        }

        # Retry up to 2 times on failure
        max_retries = 2
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(
                    "Sending request to Baidu OCR API (attempt %d/%d)...",
                    attempt,
                    max_retries,
                )
                response = requests.post(self.api_url, json=payload, headers=headers)

                if response.status_code != 200:
                    logger.error(
                        "OCR request failed with status %d: %s",
                        response.status_code,
                        response.text[:500],
                    )
                    if attempt < max_retries:
                        time.sleep(2)
                        continue
                    return None

                result = response.json()
                if "result" not in result:
                    logger.error("OCR response missing 'result': %s", result)
                    return None

                # Merge markdown from all pages and collect image URLs
                markdown_parts = []
                self._image_url_map = {}

                for page_result in result["result"]["layoutParsingResults"]:
                    md_content = page_result["markdown"]["text"]
                    markdown_parts.append(md_content)

                    # Collect image URL mappings from this page
                    if "images" in page_result["markdown"]:
                        for img_path, img_url in page_result["markdown"]["images"].items():
                            self._image_url_map[img_path] = img_url

                merged_markdown = "\n\n---\n\n".join(markdown_parts)
                logger.info(
                    "Baidu OCR succeeded: %d pages, %d chars, %d images",
                    len(markdown_parts),
                    len(merged_markdown),
                    len(self._image_url_map),
                )
                return merged_markdown

            except Exception as e:
                logger.error(
                    "OCR request failed (attempt %d/%d): %s", attempt, max_retries, e
                )
                if attempt < max_retries:
                    time.sleep(2)

        return None

    def _parse_figures(
        self,
        markdown: str,
        doc_id: str,
        image_dir: Path,
    ) -> list[FigureChunk]:
        """Parse figures from Baidu OCR markdown and download images.

        Baidu OCR returns images with 'src="imgs/xxx.png"' format in markdown
        and provides download URLs in _image_url_map.
        """
        import requests

        figures: list[FigureChunk] = []
        image_dir.mkdir(parents=True, exist_ok=True)

        # Find all image src patterns: src="imgs/xxx.png" or similar
        src_pattern = r'src="([^"]+)"'
        src_matches = re.findall(src_pattern, markdown)

        # Track which images we've already processed (avoid duplicates)
        processed_names: set[str] = set()

        for img_src in src_matches:
            # Get download URL from mapping
            img_url = self._image_url_map.get(img_src)
            if not img_url:
                logger.debug("No download URL found for %s, skipping", img_src)
                continue

            # Extract figure name from content near the image reference
            img_ref = f'src="{img_src}"'
            name = self._extract_figure_name_from_img_ref(markdown, img_ref)
            if not name:
                logger.debug("No figure name found for %s, skipping", img_src)
                continue

            # Avoid duplicates (same figure referenced multiple times)
            if name in processed_names:
                continue
            processed_names.add(name)

            name = f"{doc_id}_{name}"
            caption = self._extract_caption_from_img_ref(markdown, img_ref)

            save_path = image_dir / f"{name}.png"
            try:
                response = requests.get(img_url, stream=True, timeout=15)
                response.raise_for_status()
                save_path.write_bytes(response.content)
                logger.info("Downloaded figure: %s", name)

                figures.append(
                    FigureChunk(
                        id=None,
                        title=name,
                        type=ChunkType.FIGURE,
                        image_path=str(save_path),
                        alt_text="Refer to caption",
                        caption=caption,
                    )
                )
            except Exception as e:
                logger.error("Failed to download figure %s from %s: %s", name, img_url, e)

        return figures

    def _extract_caption_from_img_ref(self, content: str, img_ref: str) -> str:
        """Extract caption text near the image reference."""
        img_pos = content.find(img_ref)
        if img_pos == -1:
            return ""

        img_end = img_pos + len(img_ref)
        post = content[img_end : img_end + 500].lstrip()
        match = re.search(
            r"(fig(?:ure)?\.?\s*\d+[a-zA-Z]?\.*.*?)\n", post, re.IGNORECASE | re.DOTALL
        )
        return match.group(1).strip() if match else ""


# Default alias for backward compatibility
PDFExtractor = PDFExtractor_baidu
