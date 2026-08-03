"""
Papers Router - Paper search, content, metadata, and image endpoints

Handles paper-level operations (not user-specific).
Prefix: /papers
"""
import base64
import binascii
import json
import logging
import os
import re
from datetime import date as Date
from datetime import timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.utils import verify_jwt_or_service
from ..db_utils import get_index_service_url, get_paper_db
from ..limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/papers", tags=["papers"])


# ==================== Find Similar Models ====================

class FindSimilarRequest(BaseModel):
    """Request model for find_similar endpoint"""
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=10, ge=1, le=100)
    similarity_cutoff: float = Field(default=0.1, ge=-1.0, le=1.0)
    filters: Optional[Dict[str, Any]] = None
    result_types: Optional[List[str]] = None


class SimilarPaper(BaseModel):
    """Response model for a similar paper"""
    doc_id: str
    title: str
    abstract: str
    similarity: float
    authors: Optional[List[str]] = None
    categories: Optional[List[str]] = None
    published_date: Optional[str] = None
    pdf_path: Optional[str] = None
    html_path: Optional[str] = None


class FindSimilarResponse(BaseModel):
    """Response model for find_similar endpoint"""
    results: List[SimilarPaper]
    query: str
    total: int


class DailyPaper(BaseModel):
    """Paper metadata included in a published-date manifest."""

    doc_id: str
    title: str
    abstract: str
    authors: List[str]
    categories: List[str]
    published_date: str
    pdf_url: str


class PapersByDateResponse(BaseModel):
    """One cursor-paginated page of a published-date manifest."""

    date: Date
    timezone: str = "UTC"
    total: int
    papers: List[DailyPaper]
    next_cursor: Optional[str] = None


def _encode_date_cursor(published_date: Date, doc_id: str) -> str:
    payload = json.dumps(
        {"v": 1, "date": published_date.isoformat(), "doc_id": doc_id},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _decode_date_cursor(cursor: str, published_date: Date) -> str:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or payload.get("date") != published_date.isoformat()
            or not isinstance(payload.get("doc_id"), str)
            or not payload["doc_id"]
        ):
            raise ValueError
        return payload["doc_id"]
    except (binascii.Error, UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=422, detail="Invalid cursor for published_date")


def _arxiv_pdf_url(doc_id: str) -> str:
    return f"https://arxiv.org/pdf/{quote(doc_id, safe='/')}"


# ==================== Embedding Client for Backend ====================

class BackendEmbeddingClient:
    """
    Lightweight embedding client for backend service.
    Uses DashScope API for generating embeddings.
    """

    def __init__(self, api_key: str, base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
                 model: str = "text-embedding-v4", dimension: int = 2048):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.dimension = dimension
        self.logger = logging.getLogger(self.__class__.__name__)

    def get_embedding(self, text: str) -> Optional[List[float]]:
        """Get embedding for a single text"""
        if not text or not text.strip():
            return None

        try:
            url = f"{self.base_url}/embeddings"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            data = {
                "model": self.model,
                "input": text,
                "dimensions": self.dimension,
                "encoding_format": "float"
            }

            response = httpx.post(url, json=data, headers=headers, timeout=30.0)
            response.raise_for_status()

            result = response.json()
            return result.get("data", [{}])[0].get("embedding")

        except Exception as e:
            self.logger.error(f"Error getting embedding: {e}")
            return None


# Global embedding client (initialized lazily)
_embedding_client: Optional[BackendEmbeddingClient] = None
_embedding_client_config: Optional[int] = None


def get_embedding_client(request: Request) -> BackendEmbeddingClient:
    """Get or create the embedding client using app state config"""
    global _embedding_client, _embedding_client_config

    config = getattr(request.app.state, 'config', {})
    dashscope_config = config.get('dashscope', {})

    current_config_hash = hash(str(dashscope_config))
    if _embedding_client is not None and _embedding_client_config == current_config_hash:
        return _embedding_client

    api_key = dashscope_config.get("api_key") or os.environ.get("DASHSCOPE_API_KEY", "")
    base_url = dashscope_config.get("base_url") or os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    model = dashscope_config.get("embedding_model") or os.environ.get("DASHSCOPE_EMBEDDING_MODEL", "text-embedding-v4")
    dimension = int(dashscope_config.get("embedding_dimension") or os.environ.get("DASHSCOPE_EMBEDDING_DIMENSION", "2048"))

    _embedding_client = BackendEmbeddingClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        dimension=dimension
    )
    _embedding_client_config = current_config_hash

    return _embedding_client


# ==================== Papers By Published Date ====================

@router.get("/by-date", response_model=PapersByDateResponse)
@limiter.limit("30/minute")
async def get_papers_by_date(
    request: Request,
    published_date: Date = Query(..., description="UTC publication date (YYYY-MM-DD)"),
    limit: int = Query(default=100, ge=1, le=100),
    cursor: Optional[str] = Query(default=None, description="Opaque cursor returned by the previous page"),
    db: AsyncSession = Depends(get_paper_db),
    _auth=Depends(verify_jwt_or_service),
):
    """List every ingested paper published on a UTC date.

    Results use stable keyset pagination ordered by ``doc_id``. ``total`` is
    the complete number of matching papers, not the size of the current page.
    """
    cursor_doc_id = _decode_date_cursor(cursor, published_date) if cursor else None
    next_date = published_date + timedelta(days=1)
    params = {
        "start_date": f"{published_date.isoformat()}T00:00:00+00:00",
        "end_date": f"{next_date.isoformat()}T00:00:00+00:00",
    }

    try:
        date_filter = (
            "published_date >= CAST(:start_date AS TIMESTAMPTZ) "
            "AND published_date < CAST(:end_date AS TIMESTAMPTZ)"
        )
        count_result = await db.execute(
            text(f"SELECT COUNT(*) FROM papers WHERE {date_filter}"),
            params,
        )
        total = int(count_result.scalar_one())

        cursor_filter = ""
        if cursor_doc_id is not None:
            cursor_filter = " AND doc_id > :cursor_doc_id"
            params["cursor_doc_id"] = cursor_doc_id
        params["page_limit"] = limit + 1

        page_result = await db.execute(
            text(
                "SELECT doc_id, title, abstract, authors, categories, published_date "
                f"FROM papers WHERE {date_filter}{cursor_filter} "
                "ORDER BY doc_id ASC LIMIT :page_limit"
            ),
            params,
        )
        rows = page_result.fetchall()
        has_more = len(rows) > limit
        page_rows = rows[:limit]

        papers = [
            DailyPaper(
                doc_id=row[0],
                title=row[1] or "",
                abstract=row[2] or "",
                authors=row[3] or [],
                categories=row[4] or [],
                published_date=str(row[5]),
                pdf_url=_arxiv_pdf_url(row[0]),
            )
            for row in page_rows
        ]
        next_cursor = (
            _encode_date_cursor(published_date, page_rows[-1][0])
            if has_more and page_rows
            else None
        )

        return PapersByDateResponse(
            date=published_date,
            total=total,
            papers=papers,
            next_cursor=next_cursor,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error listing papers for %s: %s", published_date, e)
        raise HTTPException(status_code=500, detail="Failed to list papers by date")


# ==================== Find Similar Endpoint ====================

@router.post("/find_similar", response_model=FindSimilarResponse)
@limiter.limit("20/minute")
async def find_similar_papers(
    request_body: FindSimilarRequest,
    request: Request,
    db: AsyncSession = Depends(get_paper_db),
    _auth=Depends(verify_jwt_or_service),
):
    """
    Semantic similarity search using pgvector.

    Flow:
    1. Call DashScope API to get query embedding
    2. Build SQL query with filters
    3. Query paper_embeddings table for vector search
    4. JOIN papers table for full metadata
    5. Return results
    """
    try:
        # 1. Get query embedding
        embedding_client = get_embedding_client(request)
        query_embedding = embedding_client.get_embedding(request_body.query)

        if not query_embedding:
            logger.error(f"Failed to get embedding for query: {request_body.query[:50]}...")
            raise HTTPException(status_code=500, detail="Failed to generate query embedding")

        # 2. Build vector string (PostgreSQL vector literal format)
        embedding_str = '[' + ','.join(str(x) for x in query_embedding) + ']'

        # 3. Build SQL query
        params = {
            "cutoff": request_body.similarity_cutoff,
            "limit": request_body.top_k
        }

        # Collect filter conditions for the candidate pre-filter
        candidate_conditions = []
        if request_body.filters:
            if "exclude" in request_body.filters and "doc_ids" in request_body.filters["exclude"]:
                exclude_ids = request_body.filters["exclude"]["doc_ids"]
                if exclude_ids:
                    placeholders = ", ".join(f":exc_{i}" for i in range(len(exclude_ids)))
                    candidate_conditions.append(f"pe.doc_id NOT IN ({placeholders})")
                    for i, doc_id in enumerate(exclude_ids):
                        params[f"exc_{i}"] = doc_id

            if "include" in request_body.filters and "published_date" in request_body.filters["include"]:
                date_range = request_body.filters["include"]["published_date"]
                if len(date_range) == 2:
                    candidate_conditions.append("p.published_date::text >= :start_date AND p.published_date::text <= :end_date")
                    params["start_date"] = date_range[0]
                    params["end_date"] = date_range[1]

        if candidate_conditions:
            where_clause = " AND ".join(candidate_conditions)
            sql_str = f"""
                WITH candidates AS MATERIALIZED (
                    SELECT pe.doc_id, pe.embedding, pe.title, pe.abstract,
                           p.authors, p.categories, p.published_date,
                           p.pdf_path, p."HTML_path"
                    FROM paper_embeddings pe
                    LEFT JOIN papers p ON pe.doc_id = p.doc_id
                    WHERE {where_clause}
                )
                SELECT doc_id, title, abstract, authors, categories, published_date,
                       pdf_path, "HTML_path",
                       1 - (embedding <=> '{embedding_str}'::vector) AS similarity
                FROM candidates
                WHERE 1 - (embedding <=> '{embedding_str}'::vector) >= :cutoff
                ORDER BY embedding <=> '{embedding_str}'::vector
                LIMIT :limit
            """
        else:
            sql_str = f"""
                SELECT pe.doc_id, pe.title, pe.abstract,
                       p.authors, p.categories, p.published_date,
                       p.pdf_path, p."HTML_path",
                       1 - (pe.embedding <=> '{embedding_str}'::vector) AS similarity
                FROM paper_embeddings pe
                LEFT JOIN papers p ON pe.doc_id = p.doc_id
                WHERE 1 - (pe.embedding <=> '{embedding_str}'::vector) >= :cutoff
                ORDER BY pe.embedding <=> '{embedding_str}'::vector
                LIMIT :limit
            """

        # 4. Execute query
        logger.debug(f"SQL params (excl embedding): cutoff={params.get('cutoff')}, limit={params.get('limit')}, "
                     f"start_date={params.get('start_date')}, end_date={params.get('end_date')}, "
                     f"exclude_count={sum(1 for k in params if k.startswith('exc_'))}")
        result = await db.execute(text(sql_str), params)
        rows = result.fetchall()

        # 5. Build response
        papers = []
        for row in rows:
            papers.append(SimilarPaper(
                doc_id=row[0],
                title=row[1] or "",
                abstract=row[2] or "",
                authors=row[3] or [],
                categories=row[4] or [],
                published_date=str(row[5]) if row[5] else None,
                pdf_path=row[6],
                html_path=row[7],
                similarity=float(row[8])
            ))

        logger.info(f"Found {len(papers)} similar papers for query: {request_body.query[:50]}...")

        return FindSimilarResponse(
            results=papers,
            query=request_body.query,
            total=len(papers)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in find_similar: {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


# ==================== Find Similar BM25 Endpoint ====================

@router.post("/find_similar_bm25", response_model=FindSimilarResponse)
@limiter.limit("30/minute")
async def find_similar_papers_bm25(
    request: Request,
    request_body: FindSimilarRequest,
    db: AsyncSession = Depends(get_paper_db),
    _auth=Depends(verify_jwt_or_service),
):
    """
    Full-text similarity search using BM25 (PostgreSQL ts_rank).

    Uses the fts_rank function for ranking papers based on title and abstract
    relevance to the query. No external API calls required.

    Flow:
    1. Parse query into tsquery
    2. Build SQL query with filters
    3. Query papers table using fts_rank function
    4. Return results ranked by BM25 score
    """
    try:
        # 1. Convert query to tsquery (handle simple AND/OR for now)
        # Replace commas and multiple spaces with & for AND logic
        query_terms = request_body.query.strip()
        if not query_terms:
            raise HTTPException(status_code=400, detail="Query cannot be empty")

        # Clean and prepare query for tsquery
        # Replace common separators with & (AND)
        cleaned_query = query_terms.replace(',', ' ').replace(';', ' ').replace('|', ' ')
        # Remove extra spaces
        cleaned_query = ' '.join(cleaned_query.split())
        # Join terms with & for AND logic
        tsquery_str = ' & '.join(cleaned_query.split())

        logger.debug(f"BM25 query: '{query_terms}' -> tsquery: '{tsquery_str}'")

        # 2. Build SQL query with parameters
        params = {
            "query": tsquery_str,
            "limit": request_body.top_k,
        }

        # Collect filter conditions
        filter_conditions = []
        if request_body.filters:
            if "exclude" in request_body.filters and "doc_ids" in request_body.filters["exclude"]:
                exclude_ids = request_body.filters["exclude"]["doc_ids"]
                if exclude_ids:
                    placeholders = ", ".join(f":exc_{i}" for i in range(len(exclude_ids)))
                    filter_conditions.append(f"p.doc_id NOT IN ({placeholders})")
                    for i, doc_id in enumerate(exclude_ids):
                        params[f"exc_{i}"] = doc_id

            if "include" in request_body.filters and "published_date" in request_body.filters["include"]:
                date_range = request_body.filters["include"]["published_date"]
                if len(date_range) == 2:
                    filter_conditions.append("p.published_date::text >= :start_date AND p.published_date::text <= :end_date")
                    params["start_date"] = date_range[0]
                    params["end_date"] = date_range[1]

        # Build WHERE clause
        where_clause = ""
        if filter_conditions:
            where_clause = " AND " + " AND ".join(filter_conditions)

        # 3. Build SQL query using CTE with built-in ts_rank function
        # Use @@ operator in WHERE for GIN index acceleration, compute ts_rank once in CTE
        sql_str = f"""
            WITH ranked AS (
                SELECT p.doc_id, p.title, p.abstract, p.authors, p.categories,
                       p.published_date, p.pdf_path, p."HTML_path",
                       ts_rank(
                           to_tsvector('english', coalesce(p.title, '') || ' ' || coalesce(p.abstract, '')),
                           plainto_tsquery('english', :query)
                       ) AS similarity
                FROM papers p
                WHERE to_tsvector('english', coalesce(p.title, '') || ' ' || coalesce(p.abstract, ''))
                      @@ plainto_tsquery('english', :query)
                {where_clause}
            )
            SELECT * FROM ranked
            WHERE similarity > 0
            ORDER BY similarity DESC
            LIMIT :limit
        """

        # 4. Execute query
        logger.debug(f"BM25 SQL params: query={params.get('query')}, limit={params.get('limit')}, "
                     f"start_date={params.get('start_date')}, end_date={params.get('end_date')}, "
                     f"exclude_count={sum(1 for k in params if k.startswith('exc_'))}")
        result = await db.execute(text(sql_str), params)
        rows = result.fetchall()

        # 5. Build response
        papers = []
        for row in rows:
            papers.append(SimilarPaper(
                doc_id=row[0],
                title=row[1] or "",
                abstract=row[2] or "",
                authors=row[3] or [],
                categories=row[4] or [],
                published_date=str(row[5]) if row[5] else None,
                pdf_path=row[6],
                html_path=row[7],
                similarity=float(row[8]) if row[8] else 0.0
            ))

        logger.info(f"BM25 found {len(papers)} similar papers for query: {request_body.query[:50]}...")

        return FindSimilarResponse(
            results=papers,
            query=request_body.query,
            total=len(papers)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in find_similar_bm25: {e}")
        raise HTTPException(status_code=500, detail=f"BM25 search failed: {str(e)}")


# ==================== Image Helpers ====================

async def process_markdown_images(markdown_content: str) -> str:
    """Process image paths in markdown, replacing with OSS URLs"""

    def replace_image_path(match):
        filename = match.group(1)
        new_url = f"http://oss.paperignition.com/imgs/{filename}"
        return f"({new_url})"

    pattern1 = r'\(\.\/imgs\/\/(.*?\.png)\)'   # ./imgs//xxx.png
    pattern2 = r'\(\.\.\/imgs\/\/(.*?\.png)\)'  # ../imgs//xxx.png
    pattern3 = r'\(\.\/imgs\/(.*?\.png)\)'      # ./imgs/xxx.png
    pattern4 = r'\(\.\.\/imgs\/(.*?\.png)\)'    # ../imgs/xxx.png

    result = re.sub(pattern1, replace_image_path, markdown_content)
    result = re.sub(pattern2, replace_image_path, result)
    result = re.sub(pattern3, replace_image_path, result)
    result = re.sub(pattern4, replace_image_path, result)

    return result


# ==================== Paper Content (Global) ====================

@router.get("/content/{paper_id}")
async def get_paper_content(
    paper_id: str,
    db: AsyncSession = Depends(get_paper_db)
):
    """Get global blog content for a paper from the papers table."""
    if not paper_id or not paper_id.strip():
        raise HTTPException(status_code=422, detail="Paper ID cannot be empty")

    paper_id = paper_id.strip()
    logger.info(f"Fetching paper content for paper_id: {paper_id}")

    try:
        query = text("SELECT blog FROM papers WHERE doc_id = :paper_id")
        result = await db.execute(query, {"paper_id": paper_id})
        row = result.fetchone()

        if not row or not row[0]:
            logger.warning(f"Blog content not found for paper_id: {paper_id}")
            raise HTTPException(status_code=404, detail="Blog content not found")

        markdown_content = row[0]
        processed_content = await process_markdown_images(markdown_content)

        logger.info(f"Successfully processed paper content for paper_id: {paper_id}")
        return processed_content

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting paper content for {paper_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get paper content: {str(e)}")


# ==================== Paper Full Text (Raw Chunks) ====================

@router.get("/full_text/{doc_id}")
@limiter.limit("30/minute")
async def get_paper_full_text(
    request: Request,
    doc_id: str,
    db: AsyncSession = Depends(get_paper_db),
    _auth=Depends(verify_jwt_or_service),
):
    """Reconstruct a paper's full text by concatenating text_chunks in order."""
    if not doc_id or not doc_id.strip():
        raise HTTPException(status_code=422, detail="Document ID cannot be empty")

    doc_id = doc_id.strip()
    logger.info(f"Fetching full text for doc_id: {doc_id}")

    try:
        query = text(
            "SELECT text_content FROM text_chunks "
            "WHERE doc_id = :doc_id ORDER BY chunk_order"
        )
        result = await db.execute(query, {"doc_id": doc_id})
        rows = result.fetchall()

        if not rows:
            raise HTTPException(
                status_code=404,
                detail="No text chunks indexed for this paper. "
                       "Either the paper is not in the corpus or extraction has not completed.",
            )

        full_text = "\n\n".join(row[0] or "" for row in rows)
        return Response(content=full_text, media_type="text/markdown")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting full text for {doc_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get full text: {str(e)}")


# ==================== Paper Metadata ====================

@router.get("/metadata/{doc_id}")
async def get_paper_metadata(
    doc_id: str,
    db: AsyncSession = Depends(get_paper_db)
):
    """Get metadata for a specific paper from the papers table."""
    if not doc_id or not doc_id.strip():
        raise HTTPException(status_code=422, detail="Document ID cannot be empty")

    doc_id = doc_id.strip()

    try:
        query = text("""
            SELECT doc_id, title, abstract, authors, categories,
                   published_date, pdf_path, "HTML_path", comments, blog
            FROM papers WHERE doc_id = :doc_id
        """)
        result = await db.execute(query, {"doc_id": doc_id})
        row = result.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Metadata not found for doc_id: {doc_id}")

        metadata = {
            "doc_id": row[0],
            "title": row[1] or "",
            "abstract": row[2] or "",
            "authors": row[3] or [],
            "categories": row[4] or [],
            "published_date": str(row[5]) if row[5] else "",
            "pdf_path": row[6] or "",
            "html_path": row[7] or "",
            "comments": row[8] or "",
            "has_blog": bool(row[9]),
        }

        return metadata

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting metadata for {doc_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Image Endpoints ====================

@router.get("/image/{image_id}")
async def get_paper_image(
    image_id: str,
    index_service_url: str = Depends(get_index_service_url)
):
    """Get an image from storage via index_service."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{index_service_url}/get_image/",
                json={"image_id": image_id}
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Failed to get image: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.get("/image_storage_status/{doc_id}")
async def get_paper_image_storage_status(
    doc_id: str,
    index_service_url: str = Depends(get_index_service_url)
):
    """Get image storage status for a document via index_service."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{index_service_url}/get_image_storage_status/",
                json={"doc_id": doc_id}
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Failed to get image storage status: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
