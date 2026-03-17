"""ArxivClient: query arXiv API and return paper metadata. No file downloads."""

import logging

import arxiv

from core.models import DocSet

logger = logging.getLogger(__name__)


class ArxivClient:
    """Query arXiv API and return paper metadata."""

    def __init__(self, max_results: int | None = None):
        self.max_results = max_results

    def fetch_papers(
        self,
        start_time: str,
        end_time: str,
        categories: list[str] | None = None,
        exclude_ids: set[str] | None = None,
    ) -> list[DocSet]:
        """Query arXiv for papers in time window, return DocSet list with metadata only.

        Args:
            start_time: Start date in arXiv query format (e.g. "202601010000")
            end_time: End date in arXiv query format (e.g. "202601312359")
            categories: Category patterns (default: ["cs.*"])
            exclude_ids: Set of doc_ids to skip (replaces arxiv_pool.txt)

        Returns:
            List of DocSet with metadata populated, no file paths.
        """
        if categories is None:
            categories = ["cs.*"]
        if exclude_ids is None:
            exclude_ids = set()

        cat_query = " OR ".join(f"cat:{cat}" for cat in categories)
        query = f"({cat_query}) AND submittedDate:[{start_time} TO {end_time}]"

        search = arxiv.Search(
            query=query,
            max_results=self.max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
        )

        logger.info(
            "Querying arXiv: categories=%s, time=[%s, %s], max_results=%s",
            categories, start_time, end_time, self.max_results,
        )

        client = arxiv.Client()
        results = list(client.results(search))
        logger.info("arXiv returned %d results", len(results))

        papers: list[DocSet] = []
        for result in results:
            arxiv_id = result.entry_id.split("/")[-1]

            if arxiv_id in exclude_ids:
                logger.debug("Skipping already-processed paper: %s", arxiv_id)
                continue

            paper = DocSet(
                doc_id=arxiv_id,
                title=result.title,
                authors=[author.name for author in result.authors],
                categories=result.categories,
                published_date=str(result.published),
                abstract=result.summary,
                comments=result.comment,
                pdf_path=None,
                HTML_path=None,
            )
            papers.append(paper)

        logger.info("Returning %d new papers (excluded %d)", len(papers), len(results) - len(papers))
        return papers
