"""PaperPullService: fetch papers from arXiv, extract content via HTML (with PDF fallback)."""

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING
from zoneinfo import ZoneInfo

import requests

from core.models import DocSet
from core.arxiv import ArxivClient, HTMLExtractor, PDFExtractor, download_pdf

if TYPE_CHECKING:
    from orchestrator.storage_util import LocalStorageManager

logger = logging.getLogger(__name__)

_AR5IV_URL = "https://ar5iv.labs.arxiv.org/html/{arxiv_id}"


def _fetch_ar5iv_html(arxiv_id: str) -> Optional[str]:
    """Fetch HTML content from ar5iv for a given arXiv paper ID."""
    url = _AR5IV_URL.format(arxiv_id=arxiv_id)
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "PaperIgnition/2.0"})
        if resp.status_code == 200:
            return resp.text
        logger.warning("ar5iv returned %d for %s", resp.status_code, arxiv_id)
    except Exception as e:
        logger.warning("Failed to fetch ar5iv HTML for %s: %s", arxiv_id, e)
    return None


class PaperPullService:
    """
    Service for pulling and extracting papers from arXiv.

    Uses HTML extraction first, then PDF as fallback for papers that fail HTML.
    """

    def __init__(
        self,
        base_dir: Optional[str] = None,
        max_workers: int = 3,
        time_slots_count: int = 3,
        location: str = "Asia/Shanghai",
        count_delay: int = 1,
        max_papers: Optional[int] = None,
        storage_manager: Optional["LocalStorageManager"] = None,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.max_workers = max_workers
        self.time_slots_count = time_slots_count
        self.location = location
        self.count_delay = count_delay
        self.max_papers = max_papers
        self.storage_manager = storage_manager

        # Setup directories
        if base_dir is None:
            base_dir = os.path.dirname(__file__)
        self.base_dir = Path(base_dir)

        if storage_manager:
            self.html_text_folder = storage_manager.config.htmls_path
            self.pdf_folder_path = storage_manager.config.pdfs_path
            self.image_folder_path = storage_manager.config.imgs_path
            self.json_output_path = storage_manager.config.jsons_path
        else:
            self.html_text_folder = self.base_dir / "htmls"
            self.pdf_folder_path = self.base_dir / "pdfs"
            self.image_folder_path = self.base_dir / "imgs"
            self.json_output_path = self.base_dir / "jsons"

        self.arxiv_pool_path = self.base_dir / "html_url_storage" / "html_urls.txt"

        # VolcEngine credentials for PDF OCR fallback
        self.volcengine_ak = os.getenv("VOLCENGINE_AK", "")
        self.volcengine_sk = os.getenv("VOLCENGINE_SK", "")

        self._setup_directories()

    def _setup_directories(self):
        """Create necessary directories if they don't exist."""
        self.arxiv_pool_path.parent.mkdir(parents=True, exist_ok=True)
        self.arxiv_pool_path.touch(exist_ok=True)

        for path in [self.html_text_folder, self.pdf_folder_path,
                     self.image_folder_path, self.json_output_path]:
            Path(path).mkdir(parents=True, exist_ok=True)

    def _get_time_str(self) -> str:
        """Get UTC time string for the fetch window."""
        if self.location == "cloud":
            # Production/cloud mode: use UTC directly
            local_tz = ZoneInfo("UTC")
        else:
            local_tz = ZoneInfo(self.location)
        local_now = (datetime.now(local_tz) - timedelta(days=self.count_delay)).replace(
            second=0, microsecond=0
        )
        utc_now = local_now.astimezone(ZoneInfo("UTC"))
        return utc_now.strftime("%Y%m%d%H%M")

    def _divide_time_into_slots(self, time: str) -> List[str]:
        """Divide a 24-hour period into time slots."""
        fmt = "%Y%m%d%H%M"
        end_time = datetime.strptime(time, fmt)
        start_time = end_time - timedelta(days=1)
        total_minutes = int((end_time - start_time).total_seconds() // 60)
        step = total_minutes / self.time_slots_count

        result = []
        for i in range(self.time_slots_count + 1):
            t = start_time + timedelta(minutes=round(i * step))
            result.append(t.strftime(fmt))
        return result

    def _load_exclude_ids(self) -> set:
        """Load already-processed paper IDs from the pool file."""
        exclude = set()
        if self.arxiv_pool_path.exists():
            for line in self.arxiv_pool_path.read_text().splitlines():
                line = line.strip()
                if line:
                    exclude.add(line)
        return exclude

    def _save_to_pool(self, doc_ids: list[str]):
        """Append newly fetched paper IDs to the pool file."""
        with open(self.arxiv_pool_path, "a") as f:
            for doc_id in doc_ids:
                f.write(doc_id + "\n")

    def _extract_single_paper(self, paper: DocSet) -> DocSet:
        """Extract content for a single paper: try HTML first, then PDF fallback."""
        doc_id = paper.doc_id
        html_extractor = HTMLExtractor()

        # Step 1: Try HTML extraction via ar5iv
        html_content = _fetch_ar5iv_html(doc_id)
        if html_content:
            try:
                text_chunks, figure_chunks, table_chunks = html_extractor.extract(
                    html_content, doc_id, str(self.image_folder_path)
                )
                if text_chunks:
                    paper.text_chunks = text_chunks
                    paper.figure_chunks = figure_chunks
                    paper.table_chunks = table_chunks
                    self.logger.info("HTML extraction succeeded for %s", doc_id)
                    return paper
                else:
                    self.logger.warning("HTML extraction returned no text for %s, trying PDF", doc_id)
            except Exception as e:
                self.logger.warning("HTML extraction failed for %s: %s, trying PDF", doc_id, e)

        # Step 2: PDF fallback
        if not self.volcengine_ak or not self.volcengine_sk:
            self.logger.warning("No VolcEngine credentials, skipping PDF fallback for %s", doc_id)
            return paper

        pdf_url = f"https://arxiv.org/pdf/{doc_id}.pdf"
        pdf_path = download_pdf(pdf_url, self.pdf_folder_path, f"{doc_id}.pdf")
        if pdf_path:
            try:
                pdf_extractor = PDFExtractor(self.volcengine_ak, self.volcengine_sk)
                text_chunks, figure_chunks, table_chunks = pdf_extractor.extract(
                    pdf_path, doc_id, str(self.image_folder_path)
                )
                paper.text_chunks = text_chunks
                paper.figure_chunks = figure_chunks
                paper.table_chunks = table_chunks
                paper.pdf_path = str(pdf_path)
                self.logger.info("PDF extraction succeeded for %s", doc_id)
            except Exception as e:
                self.logger.error("PDF extraction failed for %s: %s", doc_id, e)
        else:
            self.logger.warning("PDF download failed for %s", doc_id)

        return paper

    def _serialize_doc(self, paper: DocSet):
        """Save a single DocSet to JSON."""
        json_path = Path(self.json_output_path) / f"{paper.doc_id}.json"
        try:
            json_path.write_text(paper.model_dump_json(indent=2), encoding="utf-8")
        except Exception as e:
            self.logger.error("Failed to serialize %s: %s", paper.doc_id, e)

    def _fetch_metadata_for_timeslot(self, start_str: str, end_str: str, max_papers_per_slot: Optional[int]) -> List[DocSet]:
        """Fetch metadata only (no content extraction) for a single time slot."""
        exclude_ids = self._load_exclude_ids()

        client = ArxivClient(max_results=max_papers_per_slot)
        papers = client.fetch_papers(
            start_time=start_str,
            end_time=end_str,
            exclude_ids=exclude_ids,
        )

        if not papers:
            self.logger.info("No new papers in slot %s-%s", start_str, end_str)
            return []

        self.logger.info("Fetched %d metadata entries for slot %s-%s", len(papers), start_str, end_str)
        new_ids = [p.doc_id for p in papers]
        self._save_to_pool(new_ids)
        return papers

    def _run_for_timeslot(self, start_str: str, end_str: str, max_papers_per_slot: Optional[int]) -> List[str]:
        """Fetch and extract papers for a single time slot (full mode)."""
        papers = self._fetch_metadata_for_timeslot(start_str, end_str, max_papers_per_slot)

        # Extract content for each paper
        for paper in papers:
            self._extract_single_paper(paper)
            self._serialize_doc(paper)

        return [p.doc_id for p in papers]

    def extract_paper(self, paper: DocSet) -> DocSet:
        """Public method: extract content for a single paper (HTML first, PDF fallback).

        Used by lazy mode to extract only recommended papers on demand.
        """
        return self._extract_single_paper(paper)

    def _fetch_papers_common(self, time: Optional[str] = None) -> tuple:
        """Common setup for both fetch modes. Returns (time_slots, max_papers_per_slot)."""
        if time is None:
            time = self._get_time_str()

        self.logger.info("Fetching papers for %s", time)
        if self.max_papers:
            self.logger.info("Max papers limit: %d", self.max_papers)

        time_slots = self._divide_time_into_slots(time)
        num_slots = len(time_slots) - 1

        max_papers_per_slot = None
        if self.max_papers:
            max_papers_per_slot = self.max_papers // num_slots
            if self.max_papers % num_slots != 0:
                max_papers_per_slot += 1
            self.logger.info("Max papers per time slot: %d (across %d slots)", max_papers_per_slot, num_slots)

        return time_slots, num_slots, max_papers_per_slot

    def fetch_metadata_only(self, time: Optional[str] = None) -> List[DocSet]:
        """Fetch paper metadata from arXiv without content extraction (lazy mode).

        Returns DocSet objects with metadata only (title, abstract, authors, etc.).
        Content extraction is deferred to extract_paper() for selected papers.
        """
        time_slots, num_slots, max_papers_per_slot = self._fetch_papers_common(time)

        all_papers = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = []
            for i in range(num_slots):
                start_str = time_slots[i]
                end_str = time_slots[i + 1]
                futures.append(
                    executor.submit(self._fetch_metadata_for_timeslot, start_str, end_str, max_papers_per_slot)
                )

            for f in futures:
                result = f.result()
                if result:
                    all_papers.extend(result)

        self.logger.info("Total metadata fetched: %d papers", len(all_papers))
        return all_papers

    def fetch_daily_papers(self, time: Optional[str] = None) -> List[DocSet]:
        """Fetch daily papers from arXiv with full content extraction."""
        time_slots, num_slots, max_papers_per_slot = self._fetch_papers_common(time)

        # Fetch papers in parallel using thread pool
        newly_fetched_ids = set()
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = []
            for i in range(num_slots):
                start_str = time_slots[i]
                end_str = time_slots[i + 1]
                futures.append(
                    executor.submit(self._run_for_timeslot, start_str, end_str, max_papers_per_slot)
                )

            for f in futures:
                result = f.result()
                if result:
                    newly_fetched_ids.update(result)

        self.logger.info("Newly fetched paper IDs: %d", len(newly_fetched_ids))

        # Load newly fetched papers from JSON
        new_docs = []

        if self.storage_manager:
            for doc_id in newly_fetched_ids:
                docset = self.storage_manager.load_paper_docset(doc_id)
                if docset:
                    new_docs.append(docset)
                    self.logger.info("Loaded: %s - %s", docset.doc_id, docset.title)
        else:
            for json_file in Path(self.json_output_path).glob("*.json"):
                file_name = json_file.stem
                if file_name in newly_fetched_ids:
                    try:
                        with open(json_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            docset = DocSet(**data)
                            new_docs.append(docset)
                            self.logger.info("Loaded: %s - %s", docset.doc_id, docset.title)
                    except Exception as e:
                        self.logger.error("Failed to parse %s: %s", json_file.name, e)

        self.logger.info("Total newly fetched papers: %d", len(new_docs))
        return new_docs
