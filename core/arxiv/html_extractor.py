"""HTMLExtractor: parse ar5iv HTML into text, figure, and table chunks.

Takes HTML string as input — no file I/O except image downloads.
"""

import logging
import re
from pathlib import Path

from bs4 import BeautifulSoup

from core.arxiv.downloader import get_image_from_url
from core.models import ChunkType, FigureChunk, TableChunk, TextChunk

logger = logging.getLogger(__name__)


class HTMLExtractor:
    """Extract text, figures, and tables from ar5iv HTML content."""

    def extract(
        self,
        html_content: str,
        doc_id: str,
        image_dir: Path | str,
    ) -> tuple[list[TextChunk], list[FigureChunk], list[TableChunk]]:
        """Parse HTML into chunks. Downloads images to image_dir.

        Args:
            html_content: Raw HTML string (the <article> tag content)
            doc_id: arXiv paper ID
            image_dir: Directory to save extracted images

        Returns:
            Tuple of (text_chunks, figure_chunks, table_chunks)
        """
        soup = BeautifulSoup(html_content, "html.parser")
        image_dir = Path(image_dir)

        text_chunks = self._extract_text(soup)
        figure_chunks = self._extract_figures(soup, doc_id, image_dir)
        table_chunks = self._extract_tables(soup, doc_id)

        return text_chunks, figure_chunks, table_chunks

    def _extract_text(self, soup: BeautifulSoup) -> list[TextChunk]:
        """Extract text chunks from ar5iv HTML sections."""
        all_text: list[TextChunk] = []

        try:
            article = soup.find("article")
            if article is None:
                article = soup

            sections = article.find_all("section", class_=["ltx_section", "ltx_appendix"])
            if not sections:
                return all_text

            for section in sections:
                # Remove figure tags to avoid duplication
                for figure in section.find_all("figure"):
                    figure.extract()

                section_text = section.get_text()
                section_text = section_text.replace("\n\n", "\n")
                section_id = section.get("id", "")
                title_elem = section.find("h2", class_="ltx_title ltx_title_section")
                title = title_elem.get_text(strip=True) if title_elem else ""

                all_text.append(TextChunk(
                    id=section_id,
                    type=ChunkType.TEXT,
                    title=title,
                    caption=title,
                    text=section_text,
                ))

        except Exception as e:
            logger.error("Error extracting text: %s", e)

        return all_text

    def _extract_figures(
        self,
        soup: BeautifulSoup,
        doc_id: str,
        image_dir: Path,
    ) -> list[FigureChunk]:
        """Extract figures from HTML and download images."""
        figures: list[FigureChunk] = []
        image_dir.mkdir(parents=True, exist_ok=True)

        for fig in soup.find_all(
            lambda tag: tag.name == "figure" and "ltx_table" not in tag.get("class", [])
        ):
            img = fig.find("img")
            caption = fig.find("figcaption")
            fig_id = fig.get("id", "")

            if not (img and caption):
                continue

            tag = caption.find("span", class_="ltx_tag_figure")
            if not (tag and fig_id):
                continue

            numbers = re.findall(r"\d+", fig_id)
            if len(numbers) == 2:
                figure_name = f"{doc_id}_Figure{numbers[1]}"
            elif len(numbers) > 2:
                figure_name = f"{doc_id}_Figure{numbers[1]}({numbers[2]})"
            else:
                figure_name = f"{doc_id}_Figure"

            img_src = img["src"]
            alt = img.get("alt", "")
            caption_text = caption.get_text(strip=True)

            img_data = get_image_from_url(doc_id, img_src)
            img_filename = image_dir / f"{figure_name}.png"

            if img_data:
                img_filename.write_bytes(img_data)

            figures.append(FigureChunk(
                id=fig_id,
                title=figure_name,
                type=ChunkType.FIGURE,
                image_path=str(img_filename),
                alt_text=alt,
                caption=caption_text,
            ))

        return figures

    def _extract_tables(self, soup: BeautifulSoup, doc_id: str) -> list[TableChunk]:
        """Extract tables from HTML."""
        tables: list[TableChunk] = []

        for table_fig in soup.find_all("figure", class_="ltx_table"):
            table = table_fig.find("table")
            caption = table_fig.find("figcaption")
            table_id = table_fig.get("id", "")

            if not (table and caption):
                continue

            tag = caption.find("span", class_="ltx_tag_table")
            if not tag:
                continue

            table_name = tag.text.strip().rstrip(":").strip()
            table_name = table_name.replace(" ", "")
            table_name = f"{doc_id}_{table_name}"
            table_html = str(table)
            caption_text = caption.get_text(strip=True)

            tables.append(TableChunk(
                id=table_id,
                title=table_name,
                type=ChunkType.TABLE,
                table_html=table_html,
                caption=caption_text,
            ))

        return tables
