"""
API Client Layer for PaperIgnition Orchestrator

Provides robust HTTP clients with retry logic, timeout handling, and consistent error handling.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from core.models import DocSet


class APIClientError(Exception):
    """Base exception for API client errors"""
    pass


class APIConnectionError(APIClientError):
    """Raised when unable to connect to API"""
    pass


class APIResponseError(APIClientError):
    """Raised when API returns an error response"""
    pass


class BaseAPIClient:
    """Base API client with common functionality"""

    def __init__(self, base_url: str, timeout: float = 30.0, max_retries: int = 3, verify_ssl: bool = True):
        """
        Initialize base API client

        Args:
            base_url: Base URL for the API
            timeout: Default timeout in seconds
            max_retries: Maximum number of retry attempts
            verify_ssl: Whether to verify SSL certificates
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.max_retries = max_retries
        self.verify_ssl = verify_ssl
        self.logger = logging.getLogger(self.__class__.__name__)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
        reraise=True
    )
    def _make_request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        timeout: Optional[float] = None
    ) -> httpx.Response:
        """
        Make HTTP request with retry logic

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (without base URL)
            json_data: JSON data for request body
            params: Query parameters
            timeout: Request timeout (uses default if None)

        Returns:
            httpx.Response object

        Raises:
            APIConnectionError: If connection fails after retries
            APIResponseError: If API returns error status
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        timeout_value = timeout or self.timeout

        try:
            self.logger.debug(f"Making {method} request to {url}")
            response = httpx.request(
                method=method,
                url=url,
                json=json_data,
                params=params,
                timeout=timeout_value,
                verify=self.verify_ssl
            )
            response.raise_for_status()
            return response

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            self.logger.error(f"Connection error to {url}: {e}")
            raise APIConnectionError(f"Failed to connect to {url}: {str(e)}") from e

        except httpx.HTTPStatusError as e:
            self.logger.error(f"HTTP error from {url}: {e.response.status_code} - {e.response.text}")
            raise APIResponseError(
                f"API error ({e.response.status_code}): {e.response.text}"
            ) from e

        except Exception as e:
            self.logger.error(f"Unexpected error calling {url}: {e}")
            raise APIClientError(f"Unexpected error: {str(e)}") from e

    def get(self, endpoint: str, params: Optional[Dict] = None, timeout: Optional[float] = None) -> Dict:
        """Make GET request and return JSON response"""
        response = self._make_request("GET", endpoint, params=params, timeout=timeout)
        return response.json()

    def post(self, endpoint: str, json_data: Dict, params: Optional[Dict] = None, timeout: Optional[float] = None) -> Dict:
        """Make POST request and return JSON response"""
        response = self._make_request("POST", endpoint, json_data=json_data, params=params, timeout=timeout)
        return response.json()


class BackendAPIClient(BaseAPIClient):
    """Client for Backend App Service API"""

    def __init__(self, base_url: str, timeout: float = 30.0, verify_ssl: bool = True):
        super().__init__(base_url, timeout, verify_ssl=verify_ssl)

    def get_all_users(self, active_since: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all users from backend

        Args:
            active_since: ISO date string to filter users by recent activity

        Returns:
            List of user dictionaries with username and interests

        Raises:
            APIClientError: If request fails
        """
        try:
            params = {}
            if active_since:
                params["active_since"] = active_since
                self.logger.info(f"Fetching active users (since {active_since})...")
            else:
                self.logger.info("Fetching all users...")
            users = self.get("/api/users/all", params=params or None, timeout=100.0)
            self.logger.info(f"Retrieved {len(users)} users")
            return users
        except Exception as e:
            self.logger.error(f"Failed to fetch users: {e}")
            raise

    def get_user_by_email(self, email: str) -> Dict[str, Any]:
        """
        Get user information by email

        Args:
            email: User email address

        Returns:
            User information dictionary

        Raises:
            APIClientError: If user not found or request fails
        """
        try:
            self.logger.debug(f"Fetching user: {email}")
            user = self.get(f"/api/users/by_email/{email}")
            return user
        except Exception as e:
            self.logger.error(f"Failed to fetch user {email}: {e}")
            raise

    def get_user_search_context(self, email: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """
        Get user's search context, including rewrite query and personalized profile details.

        Args:
            email: User email address

        Returns:
            Tuple of (query, profile). Profile is None if not set or empty.
        """
        try:
            user = self.get_user_by_email(email)
            profile = user.get("profile_json", None)
            query = user.get("rewrite_interest") or user.get("research_interests_text")

            self.logger.debug(f"User {email} search context - query: {query}, profile: {profile}")
            return query, profile
        except Exception as e:
            self.logger.warning(f"Failed to get search context for {email}: {e}")
            return None, None

    def get_user_papers(self, username: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get papers recommended to a user

        Args:
            username: User's username/email
            limit: Maximum number of papers to return (default 50, use higher for profile extraction)

        Returns:
            List of paper dictionaries
        """
        try:
            self.logger.debug(f"Fetching papers for user: {username}")
            papers = self.get(f"/api/digests/recommendations/{username}", params={"limit": limit})
            self.logger.info(f"User {username} has {len(papers)} papers")
            return papers
        except APIResponseError as e:
            if "404" in str(e):
                self.logger.debug(f"No papers found for {username}")
                return []
            raise
        except Exception as e:
            self.logger.error(f"Failed to fetch papers for {username}: {e}")
            return []

    def get_existing_paper_ids(self, username: str) -> List[str]:
        """
        Get list of paper IDs already recommended to user

        Args:
            username: User's username/email

        Returns:
            List of paper IDs
        """
        papers = self.get_user_papers(username)
        paper_ids = [p["id"] for p in papers if p.get("id")]
        self.logger.debug(f"User {username} has {len(paper_ids)} existing papers")
        return paper_ids

    def recommend_paper(
        self,
        username: str,
        paper_id: str,
        title: str,
        authors: str = "",
        abstract: str = "",
        url: str = "",
        content: str = "",
        blog: Optional[str] = None,
        blog_abs: Optional[str] = None,
        blog_title: Optional[str] = None,
        recommendation_reason: str = "",
        relevance_score: Optional[float] = None,
        submitted: Optional[str] = None,
        timeout: float = 100.0
    ) -> bool:
        """
        Recommend a paper to a user

        Args:
            username: User's username/email
            paper_id: Paper identifier
            title: Paper title
            authors: Paper authors (comma-separated)
            abstract: Paper abstract
            url: Paper URL
            content: Paper content
            blog: Generated blog digest
            blog_abs: Blog abstract
            blog_title: Blog title
            recommendation_reason: Reason for recommendation
            relevance_score: Relevance score
            timeout: Request timeout

        Returns:
            True if successful, False otherwise
        """
        # Truncate fields to fit database constraints (VARCHAR(255))
        def truncate(s, max_len=255):
            return s[:max_len] if s else ""

        data = {
            "username": username,
            "paper_id": paper_id,
            "title": truncate(title, 255),
            "authors": truncate(authors, 255),
            "abstract": abstract,  # Text field, no limit
            "url": truncate(url, 255),
            "content": content,  # Text field, no limit
            "blog": blog or "",  # Text field, no limit
            "blog_abs": blog_abs or "",  # Text field, no limit
            "blog_title": blog_title or "",  # Text field, no limit
            "recommendation_reason": recommendation_reason,  # Text field, no limit
            "relevance_score": relevance_score,
            "submitted": submitted or ""
        }

        try:
            self.logger.debug(f"Recommending paper {paper_id} to {username}")
            self.post(
                "/api/digests/recommend",
                params={"username": username},
                json_data=data,
                timeout=timeout
            )
            self.logger.info(f"Paper {paper_id} recommended to {username} ")
            return True

        except Exception as e:
            self.logger.error(f"Failed to recommend paper {paper_id} to {username}: {e}")
            return False

    def save_retrieve_result(
        self,
        username: str,
        query: str,
        search_strategy: str,
        retrieve_ids: List[str],
        top_k_ids: List[str],
        recommendation_date: Optional[str] = None,
        timeout: float = 5.0
    ) -> bool:
        """
        Save retrieve result to database (for reranking debugging)

        Args:
            username: Username
            query: Search query
            search_strategy: Search strategy used
            retrieve_ids: Paper IDs from retrieve_k results
            top_k_ids: Paper IDs from top_k results
            recommendation_date: Recommendation date (ISO format)
            timeout: Request timeout

        Returns:
            Whether save was successful
        """
        data = {
            "username": username,
            "query": query,
            "search_strategy": search_strategy,
            "retrieve_ids": retrieve_ids,
            "top_k_ids": top_k_ids
        }

        if recommendation_date:
            data["recommendation_date"] = recommendation_date

        try:
            self.logger.info(f"Saving retrieve result for user {username}, query: '{query[:50]}...'")
            response = self.post(
                "/api/digests/retrieve_results/save",
                json_data=data,
                timeout=timeout
            )
            self.logger.info(f"Retrieve result saved successfully (ID: {response.get('id')})")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save retrieve result: {e}")
            return False

    def recommend_papers_batch(self, username: str, papers: List[Dict[str, Any]]) -> Tuple[int, int]:
        """
        Recommend multiple papers to a user

        Args:
            username: User's username/email
            papers: List of paper dictionaries

        Returns:
            Tuple of (successful_count, failed_count)
        """
        success_count = 0
        failed_count = 0

        self.logger.info(f"Recommending {len(papers)} papers to {username}...")

        for paper in papers:
            success = self.recommend_paper(
                username=username,
                paper_id=paper.get("paper_id"),
                title=paper.get("title", ""),
                authors=paper.get("authors", ""),
                abstract=paper.get("abstract", ""),
                url=paper.get("url", ""),
                content=paper.get("content", ""),
                blog=paper.get("blog"),
                blog_abs=paper.get("blog_abs"),
                blog_title=paper.get("blog_title"),
                recommendation_reason=paper.get("recommendation_reason", ""),
                relevance_score=paper.get("relevance_score"),
                submitted=paper.get("submitted", ""),
            )

            if success:
                success_count += 1
            else:
                failed_count += 1

        self.logger.info(f"Batch complete: {success_count} succeeded, {failed_count} failed")
        return success_count, failed_count

    def find_similar(
        self,
        query: str,
        top_k: int = 10,
        similarity_cutoff: float = 0.0,
        filters: Optional[Dict] = None,
        result_include_types: Optional[List[str]] = None,
        timeout: float = 60.0
    ) -> List[DocSet]:
        """
        Find similar papers using the backend find_similar API (pgvector)

        Args:
            query: Search query text
            top_k: Number of results to return
            similarity_cutoff: Minimum similarity score threshold (default 0.0)
            filters: Optional filters (e.g., exclude doc_ids)
            result_include_types: Types of data to include in results
            timeout: Request timeout in seconds

        Returns:
            List[DocSet]: List of similar papers as DocSet objects

        Raises:
            APIClientError: If search fails
        """
        if result_include_types is None:
            result_include_types = ["metadata", "search_parameters"]

        payload = {
            "query": query,
            "top_k": top_k,
            "similarity_cutoff": similarity_cutoff,
            "search_strategies": [["vector", 0.1]],
            "filters": filters,
            "result_include_types": result_include_types
        }

        try:
            self.logger.info(
                f"Searching via backend (pgvector): '{query}' "
                f"(top_k: {top_k}, cutoff: {similarity_cutoff})"
            )

            response = self.post("/api/papers/find_similar", json_data=payload, timeout=timeout)

            # Convert results to DocSet objects
            results = response.get("results", [])
            docsets = self._convert_find_similar_results_to_docsets(results)

            self.logger.info(f"Found {len(docsets)} papers via backend")
            return docsets

        except Exception as e:
            self.logger.error(f"Backend search failed for query '{query}': {e}")
            raise

    def _convert_find_similar_results_to_docsets(self, results: List[Dict]) -> List[DocSet]:
        """Convert find_similar API results to DocSet objects"""
        docsets = []

        for r in results:
            try:
                docset_data = {
                    'doc_id': r.get('doc_id'),
                    'title': r.get('title', 'Unknown Title'),
                    'authors': r.get('authors', []),
                    'categories': r.get('categories', []),
                    'published_date': r.get('published_date', ''),
                    'abstract': r.get('abstract', ''),
                    'pdf_path': r.get('pdf_path', ''),
                    'HTML_path': r.get('html_path'),
                    'text_chunks': [],
                    'figure_chunks': [],
                    'table_chunks': [],
                    'metadata': r,
                }
                docsets.append(DocSet(**docset_data))
            except Exception as e:
                self.logger.warning(f"Failed to create DocSet for {r.get('doc_id')}: {e}")
                continue

        return docsets


    def get_users_with_boost_requested(self) -> List[str]:
        """Get list of usernames where profile_boost_requested=True (orchestrator-facing).

        Returns:
            List of usernames that have requested a profile boost.
        """
        try:
            result = self.get("/api/users/boost-requested")
            usernames = result.get("usernames", [])
            self.logger.info(f"Found {len(usernames)} users with boost requested")
            return usernames
        except Exception as e:
            self.logger.error(f"Failed to fetch boost-requested users: {e}")
            return []

    def complete_profile_boost(self, username: str, profile_json: Dict[str, Any]) -> bool:
        """Save extracted profile and reset the boost flag for a user.

        Args:
            username: User's username/email
            profile_json: Extracted profile dict (persona_definition, negative_constraints, ranking_heuristics)

        Returns:
            True if successful, False otherwise.
        """
        try:
            self.post(f"/api/users/boost-complete/{username}", json_data={"profile_json": profile_json})
            self.logger.info(f"Profile boost completed for {username}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to complete profile boost for {username}: {e}")
            return False

    def get_profile_pool(self, username: str) -> List[Dict[str, Any]]:
        """Fetch existing profile pool entries for a user.

        Args:
            username: User's username/email

        Returns:
            List of pool entry dicts with id, profile_json, metrics, etc.
        """
        try:
            entries = self.get(f"/api/users/profile-pool/{username}")
            self.logger.info(f"Loaded {len(entries)} profile pool entries for {username}")
            return entries
        except Exception as e:
            self.logger.error(f"Failed to fetch profile pool for {username}: {e}")
            return []

    def save_profile_pool(
        self,
        username: str,
        entries: List[Dict[str, Any]],
        active_entry_index: int,
    ) -> bool:
        """Save the full profile pool and set the active profile.

        Args:
            username: User's username/email
            entries: List of pool entry dicts (profile_json, generation, metrics, etc.)
            active_entry_index: Index into entries list that should be marked active

        Returns:
            True if successful, False otherwise.
        """
        try:
            self.post(
                f"/api/users/profile-pool/{username}",
                json_data={
                    "entries": entries,
                    "active_entry_index": active_entry_index,
                },
            )
            self.logger.info(
                f"Saved profile pool for {username}: {len(entries)} entries, active={active_entry_index}"
            )
            return True
        except Exception as e:
            self.logger.error(f"Failed to save profile pool for {username}: {e}")
            return False

    def record_boost_history(
        self,
        username: str,
        boost_number: int,
        cumulative_likes: int,
        pool_version: int,
        metrics: dict,
        active_profile_json: dict | None = None,
        changes_made: str | None = None,
        pool_candidates_count: int = 0,
        pool_diversity: list | None = None,
    ) -> bool:
        """Record a boost event to the append-only history table."""
        try:
            self.post(
                f"/api/users/boost-history/{username}",
                json_data={
                    "boost_number": boost_number,
                    "cumulative_likes": cumulative_likes,
                    "pool_version": pool_version,
                    "precision": metrics.get("precision"),
                    "recall": metrics.get("recall"),
                    "f1": metrics.get("f1"),
                    "active_profile_json": active_profile_json,
                    "changes_made": changes_made,
                    "pool_candidates_count": pool_candidates_count,
                    "pool_diversity": pool_diversity,
                },
            )
            self.logger.info(
                f"Recorded boost history for {username}: boost #{boost_number}, F1={metrics.get('f1')}"
            )
            return True
        except Exception as e:
            self.logger.error(f"Failed to record boost history for {username}: {e}")
            return False
