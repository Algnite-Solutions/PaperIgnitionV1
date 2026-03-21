"""
Daily Task Orchestrator for PaperIgnition v2
"""

import asyncio
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from tqdm import tqdm

from core.models import DocSet
from core.rerankers import GeminiReranker, GeminiRerankerPDF

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.api_clients import BackendAPIClient
from orchestrator.generate_blog import run_Gemini_blog_generation_recommend
from orchestrator.paper_pull import PaperPullService
from orchestrator.storage_util import (
    EmbeddingClient,
    LocalStorageManager,
    RDSConfig,
    RDSDBManager,
    StorageConfig,
    create_oss_storage_manager,
)

try:
    from orchestrator.rate_limiter import ModelRateLimiter, RateLimiter, TokenTracker
except ImportError:
    ModelRateLimiter = None
    RateLimiter = None
    TokenTracker = None


class JobLogger:
    """Simplified job logger for v2"""

    def __init__(self, config=None):
        self.config = config

    async def start_job_log(self, job_type="", username=""):
        job_id = f"{job_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        logging.info(f"Job started: {job_id} ({job_type}, {username})")
        return job_id

    async def update_job_log(self, job_id, status="", details=None):
        logging.info(f"Job {job_id}: {status} {details or ''}")

    async def complete_job_log(self, job_id, status="success", details=None, error_message=None):
        if error_message:
            logging.error(f"Job {job_id} completed: {status} - {error_message}")
        else:
            logging.info(f"Job {job_id} completed: {status} - {details or ''}")

    async def close(self):
        pass


def _substitute_env_vars(value: Any) -> Any:
    """Recursively substitute ${VAR_NAME} placeholders with environment variables."""
    if isinstance(value, str):
        def replace_env_var(match):
            env_var = match.group(1)
            env_value = os.environ.get(env_var)
            if env_value is None:
                logging.warning(f"Environment variable '{env_var}' not found, keeping placeholder")
                return match.group(0)
            return env_value
        return re.sub(r'\$\{([^}]+)\}', replace_env_var, value)
    elif isinstance(value, dict):
        return {k: _substitute_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_substitute_env_vars(item) for item in value]
    else:
        return value


def load_orchestrator_config(config_file: Optional[str] = None) -> Dict[str, Any]:
    """
    Load orchestrator configuration from YAML file.

    Args:
        config_file: Path to config file. If None, loads development config by default.

    Returns:
        Configuration dictionary
    """
    if config_file is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, "configs", "development.yaml")
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, config_file)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    config = _substitute_env_vars(config)
    return config


class PaperIgnitionOrchestrator:
    """Orchestrator for daily PaperIgnition tasks"""

    def __init__(
        self,
        orchestrator_config_file,
        stage_overrides=None,
        user_filter=None
    ):
        self.stage_overrides = stage_overrides
        self.user_filter = user_filter
        self.setup_environment()

        # Load orchestrator configuration
        self.orch_config = load_orchestrator_config(orchestrator_config_file)

        self.setup_logging()

        # Use configuration from orchestrator config
        self.backend_config = self.orch_config
        self.backend_api_url = str(self.orch_config["backend_service"]["host"])

        logging.info("Using unified configuration")
        logging.info(f"Backend API URL: {self.backend_api_url}")

        # Initialize API clients
        self.backend_client = BackendAPIClient(self.backend_api_url)

        # Initialize paper pull service with config
        base_dir = os.path.join(self.project_root, "orchestrator")
        paper_config = self.orch_config["paper_pull"]

        # Initialize storage manager first (before paper_service)
        blog_output_path = self.orch_config["blog_generation"]["output_path"]
        if not os.path.isabs(blog_output_path):
            blog_output_path = os.path.join(self.project_root, blog_output_path)

        storage_config = StorageConfig(
            base_dir=base_dir,
            blogs_dir=blog_output_path,
            jsons_dir=os.path.join(base_dir, "jsons"),
            htmls_dir=os.path.join(base_dir, "htmls"),
            pdfs_dir=os.path.join(base_dir, "pdfs"),
            imgs_dir=os.path.join(base_dir, "imgs"),
            keep_blogs=self.orch_config.get("storage", {}).get("keep_blogs", True),
            keep_jsons=self.orch_config.get("storage", {}).get("keep_jsons", True),
            keep_htmls=self.orch_config.get("storage", {}).get("keep_htmls", True),
            keep_pdfs=self.orch_config.get("storage", {}).get("keep_pdfs", True),
            keep_imgs=self.orch_config.get("storage", {}).get("keep_imgs", True),
        )
        self.storage_manager = LocalStorageManager(storage_config)
        logging.info(f"Initialized LocalStorageManager with base_dir: {base_dir}")

        # Initialize paper pull service with config and storage_manager
        self.paper_service = PaperPullService(
            base_dir=base_dir,
            max_workers=paper_config["max_workers"],
            time_slots_count=paper_config["time_slots_count"],
            location=paper_config["location"],
            count_delay=paper_config["count_delay"],
            max_papers=paper_config.get("max_papers"),
            storage_manager=self.storage_manager
        )

        # Initialize job logger
        self.job_logger = JobLogger(config=self.orch_config)

        # ==================== RDS/OSS Components ====================

        # Initialize RDS DB Manager (if enabled)
        self.rds_db_manager = None
        self.embedding_client = None
        aliyun_rds_config = self.orch_config.get("aliyun_rds", {})
        dashscope_config = self.orch_config.get("dashscope", {})

        if aliyun_rds_config.get("enabled", False) and dashscope_config.get("api_key"):
            try:
                self.embedding_client = EmbeddingClient(
                    api_key=dashscope_config.get("api_key", ""),
                    base_url=dashscope_config.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
                    model=dashscope_config.get("embedding_model", "text-embedding-v4"),
                    dimension=dashscope_config.get("embedding_dimension", 2048)
                )
                logging.info(f"Initialized EmbeddingClient with model: {dashscope_config.get('embedding_model', 'text-embedding-v4')}")

                rds_config = RDSConfig(
                    host=aliyun_rds_config.get("db_host", "localhost"),
                    port=int(aliyun_rds_config.get("db_port", 5432)),
                    database=aliyun_rds_config.get("db_name_paper", "paperignition"),
                    user=aliyun_rds_config.get("db_user", "postgres"),
                    password=aliyun_rds_config.get("db_password", ""),
                    sslmode=aliyun_rds_config.get("sslmode", "prefer")
                )
                self.rds_db_manager = RDSDBManager(rds_config, self.embedding_client)
                logging.info(f"Initialized RDSDBManager for {rds_config.host}:{rds_config.port}/{rds_config.database}")

            except Exception as e:
                logging.warning(f"Failed to initialize RDS/Embedding components: {e}. Falling back to Index Service.")
                self.rds_db_manager = None
                self.embedding_client = None

        # Initialize OSS Storage Manager (if enabled)
        self.oss_storage_manager = None
        aliyun_oss_config = self.orch_config.get("aliyun_oss", {})

        if aliyun_oss_config.get("enabled", False):
            try:
                self.oss_storage_manager = create_oss_storage_manager(
                    base_dir=base_dir,
                    oss_config=aliyun_oss_config,
                    storage_options={
                        "blogs_dir": blog_output_path,
                        "jsons_dir": os.path.join(base_dir, "jsons"),
                        "htmls_dir": os.path.join(base_dir, "htmls"),
                        "pdfs_dir": os.path.join(base_dir, "pdfs"),
                        "imgs_dir": os.path.join(base_dir, "imgs"),
                    }
                )
                logging.info(f"Initialized AliyunOSSStorageManager for bucket: {aliyun_oss_config.get('bucket_name')}")
            except Exception as e:
                logging.warning(f"Failed to initialize OSS Storage Manager: {e}. Falling back to local storage.")
                self.oss_storage_manager = None

        # Initialize rate limiters from model configuration
        models_config = self.orch_config.get("models", {})
        self.models_config = models_config
        if ModelRateLimiter is not None:
            try:
                self.model_rate_limiters = ModelRateLimiter(models_config)
                logging.info(f"Initialized rate limiters for models: {list(models_config.keys())}")
            except Exception as e:
                logging.warning(f"Failed to initialize rate limiters: {e}. Rate limiting disabled.")
                self.model_rate_limiters = None
        else:
            logging.warning("ModelRateLimiter not available, rate limiting disabled")
            self.model_rate_limiters = None

        # Initialize token tracker
        if TokenTracker is not None:
            self.token_tracker = TokenTracker()
            logging.info("Initialized TokenTracker for tracking token usage")
        else:
            logging.warning("TokenTracker not available, token tracking disabled")
            self.token_tracker = None

    def setup_logging(self):
        """Setup logging configuration"""
        logs_dir = Path(__file__).parent / "logs"
        logs_dir.mkdir(exist_ok=True)
        log_file = logs_dir / "paperignition_execution.log"

        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

        file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)

        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)
        root_logger.setLevel(logging.INFO)

        for noisy in ("sqlalchemy.engine", "sqlalchemy.pool", "httpx", "httpcore", "urllib3"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    def setup_environment(self):
        """Setup environment variables and paths"""
        self.project_root = str(Path(__file__).parent.parent)
        env_file = Path(self.project_root) / ".env"
        if env_file.exists():
            from dotenv import load_dotenv
            load_dotenv(env_file, override=False)
        os.environ['PYTHONPATH'] = self.project_root
        os.chdir(self.project_root)

    async def run_fetch_daily_papers(self) -> List[DocSet]:
        """Fetch daily papers using paper_pull module.

        In lazy mode: fetches metadata only (fast), stores to RDS, generates embeddings.
        In full mode: fetches metadata + extracts content for all papers.
        """
        lazy_mode = self.orch_config.get("paper_pull", {}).get("lazy_mode", False)
        logging.info(f"Starting daily paper fetch... (lazy_mode={lazy_mode})")
        job_id = await self.job_logger.start_job_log(job_type="daily_paper_fetch", username="system")

        success = False
        papers = []
        try:
            # Load existing paper IDs from RDS to avoid re-fetching
            if self.rds_db_manager is not None:
                self.paper_service.exclude_ids = self.rds_db_manager.get_all_doc_ids()
                logging.info(f"Loaded {len(self.paper_service.exclude_ids)} existing paper IDs from RDS for dedup")

            if lazy_mode:
                # Lazy mode: metadata only — content extraction deferred to recommendation stage
                papers = self.paper_service.fetch_metadata_only()
            else:
                # Full mode: metadata + content extraction for all papers
                papers = self.paper_service.fetch_daily_papers()
            logging.info(f"Fetched {len(papers)} papers from arXiv (lazy_mode={lazy_mode})")

            # Store papers and generate embeddings
            if papers:
                if self.rds_db_manager is not None:
                    logging.info("Storing papers to RDS...")

                    new_count = 0
                    existing_count = 0
                    failed_count = 0
                    pbar = tqdm(papers, desc="Inserting papers to RDS", unit="paper")
                    for paper in pbar:
                        result = self.rds_db_manager.insert_paper(paper)
                        if result is True:
                            new_count += 1
                            if paper.text_chunks:
                                self.rds_db_manager.insert_text_chunks(paper.doc_id, paper.text_chunks)
                        elif result is False:
                            existing_count += 1
                        else:
                            failed_count += 1
                        pbar.set_postfix(new=new_count, existing=existing_count, failed=failed_count)

                    logging.info(f"RDS insert: {new_count} new, {existing_count} existing, {failed_count} failed (total {len(papers)})")

                    # Batch generate and store embeddings (from title+abstract, works in both modes)
                    if self.embedding_client:
                        paper_texts = [f"{p.title}. {p.abstract}" for p in papers]
                        embeddings = self.embedding_client.get_embeddings(
                            paper_texts,
                            batch_size=self.orch_config.get("dashscope", {}).get("batch_size", 10),
                            delay=self.orch_config.get("dashscope", {}).get("delay_between_batches", 0.5)
                        )
                        paper_data = [
                            {"doc_id": p.doc_id, "title": p.title, "abstract": p.abstract}
                            for p in papers
                        ]
                        success_emb, failed_emb = self.rds_db_manager.batch_insert_embeddings(paper_data, embeddings)
                        logging.info(f"Embeddings: {success_emb} succeeded, {failed_emb} failed")

                    # Upload images to OSS (skip in lazy mode — no images yet)
                    if not lazy_mode and self.oss_storage_manager and self.orch_config["constants"]["store_images_on_index"]:
                        for paper in papers:
                            if paper.figure_chunks:
                                results = self.oss_storage_manager.upload_images_from_docset(paper)
                                success_imgs = sum(1 for v in results.values() if v)
                                logging.debug(f"Uploaded {success_imgs} images for paper {paper.doc_id}")

            success = len(papers) > 0
            logging.info(f"Daily paper fetch complete. Fetched {len(papers)} papers.")

            status = "success" if success else "failed"
            details = f"Fetched {len(papers)} papers (lazy={lazy_mode})" if success else "Paper fetch failed"
            await self.job_logger.complete_job_log(job_id, status=status, details={"message": details})

        except Exception as e:
            await self.job_logger.complete_job_log(job_id, status="failed", error_message=str(e))
            raise

        return papers


    def _ensure_pdf_downloaded(self, doc_id: str) -> Optional[str]:
        """Return local PDF path, downloading from arXiv if not already present."""
        local_path = self.storage_manager.get_pdf_path(doc_id)
        if local_path:
            return local_path
        url = f"https://arxiv.org/pdf/{doc_id}.pdf"
        try:
            import requests
            logging.info(f"Downloading PDF for {doc_id} from {url}")
            resp = requests.get(url, timeout=30, headers={"User-Agent": "PaperIgnition/1.0"})
            if resp.status_code == 200:
                self.storage_manager.save_pdf(doc_id, resp.content)
                return self.storage_manager.get_pdf_path(doc_id)
            else:
                logging.warning(f"Failed to download PDF for {doc_id}: HTTP {resp.status_code}")
        except Exception as e:
            logging.warning(f"Failed to download PDF for {doc_id}: {e}")
        return None

    async def blog_generation_for_all_users(self):
        """Generate blog digests for all users based on their interests"""
        # Only serve users active in the last 30 days (at least 1 viewed recommendation)
        active_days = self.orch_config.get("user_recommendation", {}).get("active_days", 30)
        active_since = (datetime.now(timezone.utc) - timedelta(days=active_days)).strftime('%Y-%m-%d')
        all_users = self.backend_client.get_all_users(active_since=active_since)
        logging.info(f"Found {len(all_users)} active users (viewed in last {active_days} days)")

        # Always include Demo User
        active_usernames = {u.get("username") for u in all_users}
        demo_username = self.orch_config.get("user_recommendation", {}).get("always_include_user", "Demo User")
        if demo_username and demo_username not in active_usernames:
            try:
                demo_user = self.backend_client.get_user_by_email(demo_username)
                all_users.append(demo_user)
                logging.info(f"Added always-include user: {demo_username}")
            except Exception as e:
                logging.warning(f"Could not fetch always-include user '{demo_username}': {e}")

        logging.info(f"Starting recommendation for {len(all_users)} users")
        if self.user_filter:
            all_users = [u for u in all_users if u.get("username") in self.user_filter]
            logging.info(f"Filtered to {len(all_users)} users: {self.user_filter}")

        customized_rerank = self.orch_config["user_recommendation"].get("customized_recommendation", False)
        if customized_rerank:
            recommendation_model_id = self.orch_config.get("models", {}).get("recommendation", {}).get("model_id", "gemini-2.5-pro")
            use_pdf = self.orch_config["user_recommendation"].get("use_pdf_reranker", True)
            if use_pdf:
                customized_reranker = GeminiRerankerPDF(model_name=recommendation_model_id)
            else:
                customized_reranker = GeminiReranker(model_name=recommendation_model_id)
        else:
            customized_reranker = None

        for user in all_users:
            username = user.get("username")
            if username == "BlogBot@gmail.com":
                continue
            job_id = await self.job_logger.start_job_log(job_type="daily_blog_generation", username=username)

            query, profile = self.backend_client.get_user_search_context(username)

            logging.info(f"[{username}] Reranker: {type(customized_reranker).__name__ if customized_reranker else 'None'} | Profile: {'yes' if profile else 'no'}")
            logging.info(f"[{username}] Query: {query}")
            if not query:
                logging.warning(f"[{username}] No research interests found, skipping recommendation.")
                continue

            # Get existing paper recommendations to filter out
            existing_paper_ids = self.backend_client.get_existing_paper_ids(username)
            if existing_paper_ids:
                logging.info(f"[{username}] {len(existing_paper_ids)} existing paper recommendations found")

            # Build date filter
            end_date = datetime.now(timezone.utc).strftime('%Y-%m-%d 23:59:59+00:00')
            search_days = self.orch_config.get("user_recommendation", {}).get("search_days", 5)
            start_date = (datetime.now(timezone.utc) - timedelta(days=search_days)).strftime('%Y-%m-%d 00:00:00+00:00')

            filter_params = None
            if existing_paper_ids:
                filter_params = {
                    "include": {
                        "published_date": [start_date, end_date]
                    },
                    "exclude": {
                        "doc_ids": existing_paper_ids
                    }
                }
                logging.info(f"[{username}] Excluding {len(existing_paper_ids)} existing paper IDs from search")

            # Search for papers matching the query
            user_rec_config = self.orch_config["user_recommendation"]
            top_k = user_rec_config["top_k"]
            retrieve_k = user_rec_config.get("retrieve_k", top_k)
            retrieve_result = user_rec_config.get("user_retrieve_result", False)
            logging.debug(f"similarity_cutoff: {user_rec_config['similarity_cutoff']}")

            all_search_results = self.backend_client.find_similar(
                query=query,
                top_k=retrieve_k,
                similarity_cutoff=user_rec_config["similarity_cutoff"],
                filters=filter_params
            )

            if customized_rerank:
                candidate_ids = [p.doc_id for p in all_search_results]
                if isinstance(customized_reranker, GeminiRerankerPDF):
                    pdf_paths_dict = {}
                    for p in all_search_results:
                        local_path = self._ensure_pdf_downloaded(p.doc_id)
                        if local_path:
                            pdf_paths_dict[p.doc_id] = local_path
                        else:
                            logging.warning(f"PDF unavailable for {p.doc_id}, skipping for reranking")
                    reranked_ids, thought_summary = customized_reranker.rerank(
                        query=query,
                        pdf_paths_dict=pdf_paths_dict,
                        retrieve_ids=candidate_ids,
                        top_k=top_k,
                        user_profile=profile
                    )
                else:
                    corpus_dict = {p.doc_id: p.abstract for p in all_search_results}
                    reranked_ids = customized_reranker.rerank(
                        query=query,
                        corpus_dict=corpus_dict,
                        retrieve_ids=candidate_ids,
                        top_k=top_k
                    )
                papers = []
                for p in all_search_results:
                    if p.doc_id in reranked_ids:
                        papers.append(p)
            else:
                papers = all_search_results[:top_k] if len(all_search_results) > top_k else all_search_results

            if retrieve_result and retrieve_k:
                retrieve_ids = [p.doc_id for p in all_search_results]
                top_k_ids = [p.doc_id for p in papers]

                save_success = self.backend_client.save_retrieve_result(
                    username=username,
                    query=query,
                    search_strategy=user_rec_config["search_strategy"],
                    retrieve_ids=retrieve_ids,
                    top_k_ids=top_k_ids
                )

                if save_success:
                    logging.info(
                        f"Saved retrieve result: {len(retrieve_ids)} retrieve papers, "
                        f"{len(top_k_ids)} top_k papers for query '{query}'"
                    )
                else:
                    logging.warning(f"Failed to save retrieve result for query '{query}'")

            all_papers = papers
            logging.info(f"[{username}] Found {len(all_search_results)} candidates -> reranked to {len(all_papers)} papers")

            # Lazy mode: extract content for recommended papers on demand
            lazy_mode = self.orch_config.get("paper_pull", {}).get("lazy_mode", False)
            if lazy_mode:
                logging.info(f"[{username}] Lazy mode: extracting content for {len(all_papers)} recommended papers...")
                for p in all_papers:
                    if not p.text_chunks:
                        self.paper_service.extract_paper(p)
                        if p.text_chunks:
                            # Store extracted content to RDS
                            if self.rds_db_manager is not None:
                                self.rds_db_manager.insert_text_chunks(p.doc_id, p.text_chunks)
                            # Upload images to OSS
                            if self.oss_storage_manager and p.figure_chunks:
                                self.oss_storage_manager.upload_images_from_docset(p)
                logging.info(f"[{username}] Content extraction complete for recommended papers")

            # Resolve PDF paths to local copies before blog generation
            for p in all_papers:
                local_path = self._ensure_pdf_downloaded(p.doc_id)
                if local_path:
                    p.pdf_path = local_path
                    logging.info(f"PDF available for {p.doc_id} at {local_path}")
                else:
                    p.pdf_path = None

            # Generate blog digests
            logging.info("Generating blog digests for users...")
            if all_papers:
                output_path = str(self.storage_manager.config.blogs_path)

                recommend_config = self.models_config.get("recommendation", {})
                recommend_limiter = self.model_rate_limiters.get_limiter("recommendation") if self.model_rate_limiters else None
                run_Gemini_blog_generation_recommend(
                    all_papers,
                    output_path=output_path,
                    model_config=recommend_config,
                    rate_limiter=recommend_limiter,
                    token_tracker=self.token_tracker,
                    username=username
                )
                logging.info("Digest generation complete.")

                paper_infos = []
                for paper in all_papers:
                    blog = self.storage_manager.read_blog(paper.doc_id)
                    paper_infos.append({
                        "paper_id": paper.doc_id,
                        "title": paper.title,
                        "authors": ", ".join(paper.authors),
                        "abstract": paper.abstract,
                        "url": "https://arxiv.org/pdf/" + paper.doc_id,
                        "content": paper.abstract,
                        "blog": blog,
                        "recommendation_reason": "This is a dummy recommendation reason for paper " + paper.title,
                        "relevance_score": 0.5,
                        "submitted": paper.published_date,
                    })

                # Write recommendations
                self.backend_client.recommend_papers_batch(username, paper_infos)

                # Log token usage summary for this user
                if self.token_tracker:
                    self.token_tracker.log_summary(username)

                await self.job_logger.complete_job_log(job_id=job_id, details=f"Recommended {len(paper_infos)} papers.")
            else:
                logging.warning(f"[{username}] No relevant papers found, skipping blog generation and recommendation.")
                await self.job_logger.complete_job_log(job_id=job_id, status="failed", details="No relevant papers found.")
                continue

    async def run_per_user_blog_generation(self):
        """Run recommendation generation task for each user"""
        logging.info("Starting recommendation generation...")
        logging.info("Starting blog generation for existing users...")
        await self.blog_generation_for_all_users()
        logging.info("Blog generation for existing users complete.")

    async def run_all_tasks(self):
        """Run all daily tasks based on configuration and return results"""
        start_time = datetime.now()
        logging.info(f"Starting all daily tasks at {start_time}")

        # Get stage configuration
        stages = dict(self.orch_config["stages"])
        if self.stage_overrides:
            for key in stages:
                stages[key] = key in self.stage_overrides
        parallel_execution = self.orch_config["job_execution"]["enable_parallel_blog_generation"]

        overall_job_id = await self.job_logger.start_job_log(job_type="daily_tasks_orchestrator", username="system")

        results = {
            "start_time": start_time.isoformat(),
            "paper_fetch": False,
            "all_papers_blog_generation": False,
            "per_user_blog_generation": False,
            "papers_count": 0,
            "stages_run": []
        }

        try:
            papers = []

            # === Step 1: Fetch and Index Papers ===
            if stages.get("fetch_daily_papers", False):
                logging.info("=== Step 1: Fetching daily papers ===")
                results["stages_run"].append("fetch_daily_papers")
                await self.job_logger.update_job_log(overall_job_id, status="running", details={"step": "paper_fetch"})

                papers = await self.run_fetch_daily_papers()
                results["papers_fetched"] = len(papers)
                results["paper_fetch"] = len(papers) > 0

                if len(papers) == 0:
                    logging.warning("No papers fetched, skipping downstream tasks")
                    await self.job_logger.complete_job_log(
                        overall_job_id,
                        status="partial",
                        details={"reason": "No papers were fetched", "stages_run": results["stages_run"]}
                    )
                    return results
            else:
                logging.info("Skipping paper fetch stage (disabled in config)")

            # === Step 2: Blog Generation ===
            if stages.get("generate_per_user_blogs", False):
                logging.info("=== Step 2: Blog generation ===")
                await self.job_logger.update_job_log(overall_job_id, status="running", details={"step": "blog_generation"})

                try:
                    tasks = []

                    if stages.get("generate_per_user_blogs", False):
                        results["stages_run"].append("generate_per_user_blogs")
                        tasks.append(("per_user", self.run_per_user_blog_generation()))

                    if parallel_execution and len(tasks) > 1:
                        logging.info("Running blog generation tasks in parallel")
                        blog_gen_results = await asyncio.gather(
                            *[task[1] for task in tasks],
                            return_exceptions=True
                        )
                        for i, (task_name, _) in enumerate(tasks):
                            result = blog_gen_results[i]
                            if isinstance(result, Exception):
                                logging.error(f"{task_name} blog generation failed: {result}")
                                results[f"{task_name}_blog_generation"] = False
                            else:
                                results[f"{task_name}_blog_generation"] = True
                    else:
                        logging.info("Running blog generation tasks sequentially")
                        for task_name, task_coro in tasks:
                            try:
                                await task_coro
                                results[f"{task_name}_blog_generation"] = True
                            except Exception as e:
                                logging.error(f"{task_name} blog generation failed: {e}")
                                results[f"{task_name}_blog_generation"] = False

                except Exception as e:
                    logging.error(f"Blog generation tasks failed: {e}")
                    results["error"] = str(e)
            else:
                logging.info("Skipping all blog generation stages (disabled in config)")

            # Complete overall job
            success_conditions = []
            if stages.get("fetch_daily_papers", False):
                success_conditions.append(results["paper_fetch"])
            if stages.get("generate_per_user_blogs", False):
                success_conditions.append(results.get("per_user_blog_generation", True))

            final_status = "success" if all(success_conditions) else "partial"

            await self.job_logger.complete_job_log(
                overall_job_id,
                status=final_status,
                details=results
            )

            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            logging.info(f"=== All daily tasks completed in {duration:.2f} seconds ===")
            logging.info(f"Results: {results}")

            return results

        except Exception as e:
            logging.error(f"Daily tasks orchestrator failed: {e}")
            await self.job_logger.complete_job_log(
                overall_job_id,
                status="failed",
                error_message=str(e),
                details=results
            )
            raise
        finally:
            await self.job_logger.close()


# Main execution
async def main(config_file: Optional[str] = None, stage_overrides=None, user_filter=None):
    orchestrator = PaperIgnitionOrchestrator(config_file, stage_overrides=stage_overrides, user_filter=user_filter)

    try:
        results = await orchestrator.run_all_tasks()
        return results
    except Exception as e:
        logging.error(f"Orchestration failed: {e}")
        raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PaperIgnition Orchestrator v2")
    parser.add_argument("config", nargs="?", default=None,
                        help="Config file path (default: configs/development.yaml)")
    parser.add_argument("--stages", nargs="+",
                        help="Stages to run, overrides config. Options: fetch_daily_papers, generate_per_user_blogs")
    parser.add_argument("--users", nargs="+",
                        help="Limit processing to specific usernames (e.g. --users foo@bar.com demo@example.com)")
    args = parser.parse_args()
    asyncio.run(main(args.config, stage_overrides=args.stages, user_filter=args.users))
