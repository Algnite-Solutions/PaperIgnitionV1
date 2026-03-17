"""
Storage Manager Module for PaperIgnition v2

Provides abstract base class and implementations for managing storage of:
- Blog files (.md)
- Paper JSON files (.json)
- HTML files
- PDF files
- Image files

Also provides:
- EmbeddingClient: DashScope API client for embeddings
- RDSDBManager: Aliyun RDS PostgreSQL manager with pgvector support
- AliyunOSSStorageManager: Aliyun OSS storage manager
"""

import json
import logging
import os
import shutil
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import psycopg2

from core.models import DocSet


@dataclass
class StorageConfig:
    """Configuration for storage paths"""
    base_dir: str
    blogs_dir: str = "blogs"
    jsons_dir: str = "jsons"
    htmls_dir: str = "htmls"
    pdfs_dir: str = "pdfs"
    imgs_dir: str = "imgs"

    # Cleanup options
    keep_blogs: bool = True
    keep_jsons: bool = True
    keep_htmls: bool = True
    keep_pdfs: bool = True
    keep_imgs: bool = True

    def __post_init__(self):
        """Convert relative paths to absolute paths based on base_dir"""
        self.blogs_path = self._resolve_path(self.blogs_dir)
        self.jsons_path = self._resolve_path(self.jsons_dir)
        self.htmls_path = self._resolve_path(self.htmls_dir)
        self.pdfs_path = self._resolve_path(self.pdfs_dir)
        self.imgs_path = self._resolve_path(self.imgs_dir)

    def _resolve_path(self, dir_name: str) -> Path:
        """Resolve directory path"""
        if os.path.isabs(dir_name):
            return Path(dir_name)
        return Path(self.base_dir) / dir_name


class StorageManager(ABC):
    """
    Abstract base class for storage management.

    Defines the interface for CRUD operations on different data types:
    - Blogs
    - Papers (JSON)
    - HTML files
    - PDF files
    - Images
    """

    def __init__(self, config: StorageConfig):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)

    # ==================== Blog Operations ====================

    @abstractmethod
    def save_blog(self, doc_id: str, content: str) -> bool:
        """Save blog content for a paper"""
        pass

    @abstractmethod
    def read_blog(self, doc_id: str) -> Optional[str]:
        """Read blog content for a paper"""
        pass

    @abstractmethod
    def delete_blog(self, doc_id: str) -> bool:
        """Delete blog file for a paper"""
        pass

    @abstractmethod
    def blog_exists(self, doc_id: str) -> bool:
        """Check if blog exists for a paper"""
        pass

    @abstractmethod
    def list_blogs(self) -> List[str]:
        """List all blog doc_ids"""
        pass

    # ==================== Paper JSON Operations ====================

    @abstractmethod
    def save_paper_json(self, doc_id: str, data: Dict[str, Any]) -> bool:
        """Save paper data as JSON"""
        pass

    @abstractmethod
    def read_paper_json(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Read paper data from JSON"""
        pass

    @abstractmethod
    def delete_paper_json(self, doc_id: str) -> bool:
        """Delete paper JSON file"""
        pass

    @abstractmethod
    def paper_json_exists(self, doc_id: str) -> bool:
        """Check if paper JSON exists"""
        pass

    @abstractmethod
    def list_paper_jsons(self) -> List[str]:
        """List all paper JSON doc_ids"""
        pass

    # ==================== HTML Operations ====================

    @abstractmethod
    def save_html(self, doc_id: str, content: str) -> bool:
        """Save HTML content for a paper"""
        pass

    @abstractmethod
    def read_html(self, doc_id: str) -> Optional[str]:
        """Read HTML content for a paper"""
        pass

    @abstractmethod
    def delete_html(self, doc_id: str) -> bool:
        """Delete HTML file for a paper"""
        pass

    @abstractmethod
    def html_exists(self, doc_id: str) -> bool:
        """Check if HTML exists for a paper"""
        pass

    # ==================== PDF Operations ====================

    @abstractmethod
    def save_pdf(self, doc_id: str, content: bytes) -> bool:
        """Save PDF content for a paper"""
        pass

    @abstractmethod
    def read_pdf(self, doc_id: str) -> Optional[bytes]:
        """Read PDF content for a paper"""
        pass

    @abstractmethod
    def delete_pdf(self, doc_id: str) -> bool:
        """Delete PDF file for a paper"""
        pass

    @abstractmethod
    def pdf_exists(self, doc_id: str) -> bool:
        """Check if PDF exists for a paper"""
        pass

    @abstractmethod
    def get_pdf_path(self, doc_id: str) -> Optional[str]:
        """Get the path to PDF file (for external tools that need file path)"""
        pass

    # ==================== Image Operations ====================

    @abstractmethod
    def save_image(self, doc_id: str, image_id: str, content: bytes) -> bool:
        """Save image content"""
        pass

    @abstractmethod
    def read_image(self, doc_id: str, image_id: str) -> Optional[bytes]:
        """Read image content"""
        pass

    @abstractmethod
    def delete_image(self, doc_id: str, image_id: str) -> bool:
        """Delete image file"""
        pass

    @abstractmethod
    def image_exists(self, doc_id: str, image_id: str) -> bool:
        """Check if image exists"""
        pass

    @abstractmethod
    def list_images(self, doc_id: str) -> List[str]:
        """List all image IDs for a paper"""
        pass

    @abstractmethod
    def get_image_path(self, doc_id: str, image_id: str) -> Optional[str]:
        """Get the path to image file"""
        pass

    # ==================== Bulk Operations ====================

    @abstractmethod
    def cleanup_paper_files(self, doc_id: str,
                           delete_blog: bool = False,
                           delete_json: bool = False,
                           delete_html: bool = False,
                           delete_pdf: bool = False,
                           delete_images: bool = False) -> Dict[str, bool]:
        """Clean up files for a specific paper based on flags."""
        pass

    @abstractmethod
    def cleanup_all(self,
                   delete_blogs: bool = False,
                   delete_jsons: bool = False,
                   delete_htmls: bool = False,
                   delete_pdfs: bool = False,
                   delete_images: bool = False) -> Dict[str, int]:
        """Clean up all files based on flags."""
        pass


class LocalStorageManager(StorageManager):
    """
    Local filesystem implementation of StorageManager.

    Stores files in local directories:
    - blogs/: .md files
    - jsons/: .json files
    - htmls/: .html files
    - pdfs/: .pdf files
    - imgs/: image files (organized by doc_id)
    """

    def __init__(self, config: StorageConfig):
        super().__init__(config)
        self._ensure_directories()

    def _ensure_directories(self):
        """Create necessary directories if they don't exist"""
        for path in [self.config.blogs_path, self.config.jsons_path,
                     self.config.htmls_path, self.config.pdfs_path,
                     self.config.imgs_path]:
            path.mkdir(parents=True, exist_ok=True)
            self.logger.debug(f"Ensured directory exists: {path}")

    # ==================== Blog Operations ====================

    def save_blog(self, doc_id: str, content: str) -> bool:
        """Save blog content as .md file"""
        try:
            file_path = self.config.blogs_path / f"{doc_id}.md"
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            self.logger.debug(f"Saved blog: {file_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save blog {doc_id}: {e}")
            return False

    def read_blog(self, doc_id: str) -> Optional[str]:
        """Read blog content from .md file"""
        try:
            file_path = self.config.blogs_path / f"{doc_id}.md"
            if not file_path.exists():
                self.logger.debug(f"Blog not found: {file_path}")
                return None
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            self.logger.error(f"Failed to read blog {doc_id}: {e}")
            return None

    def delete_blog(self, doc_id: str) -> bool:
        """Delete blog .md file"""
        try:
            file_path = self.config.blogs_path / f"{doc_id}.md"
            if file_path.exists():
                file_path.unlink()
                self.logger.debug(f"Deleted blog: {file_path}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Failed to delete blog {doc_id}: {e}")
            return False

    def blog_exists(self, doc_id: str) -> bool:
        """Check if blog .md file exists"""
        return (self.config.blogs_path / f"{doc_id}.md").exists()

    def list_blogs(self) -> List[str]:
        """List all blog doc_ids"""
        return [f.stem for f in self.config.blogs_path.glob("*.md")]

    # ==================== Paper JSON Operations ====================

    def save_paper_json(self, doc_id: str, data: Dict[str, Any]) -> bool:
        """Save paper data as JSON file"""
        try:
            file_path = self.config.jsons_path / f"{doc_id}.json"
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.logger.debug(f"Saved paper JSON: {file_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save paper JSON {doc_id}: {e}")
            return False

    def read_paper_json(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Read paper data from JSON file"""
        try:
            file_path = self.config.jsons_path / f"{doc_id}.json"
            if not file_path.exists():
                self.logger.debug(f"Paper JSON not found: {file_path}")
                return None
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to read paper JSON {doc_id}: {e}")
            return None

    def delete_paper_json(self, doc_id: str) -> bool:
        """Delete paper JSON file"""
        try:
            file_path = self.config.jsons_path / f"{doc_id}.json"
            if file_path.exists():
                file_path.unlink()
                self.logger.debug(f"Deleted paper JSON: {file_path}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Failed to delete paper JSON {doc_id}: {e}")
            return False

    def paper_json_exists(self, doc_id: str) -> bool:
        """Check if paper JSON file exists"""
        return (self.config.jsons_path / f"{doc_id}.json").exists()

    def list_paper_jsons(self) -> List[str]:
        """List all paper JSON doc_ids"""
        return [f.stem for f in self.config.jsons_path.glob("*.json")]

    def load_paper_docset(self, doc_id: str) -> Optional[DocSet]:
        """Load paper JSON and convert to DocSet object."""
        data = self.read_paper_json(doc_id)
        if data is None:
            return None
        try:
            return DocSet(**data)
        except Exception as e:
            self.logger.error(f"Failed to create DocSet from {doc_id}: {e}")
            return None

    def load_all_paper_docsets(self, doc_ids: Optional[List[str]] = None) -> List[DocSet]:
        """Load multiple papers as DocSet objects."""
        if doc_ids is None:
            doc_ids = self.list_paper_jsons()

        docsets = []
        for doc_id in doc_ids:
            docset = self.load_paper_docset(doc_id)
            if docset is not None:
                docsets.append(docset)

        return docsets

    # ==================== HTML Operations ====================

    def save_html(self, doc_id: str, content: str) -> bool:
        """Save HTML content"""
        try:
            file_path = self.config.htmls_path / f"{doc_id}.html"
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            self.logger.debug(f"Saved HTML: {file_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save HTML {doc_id}: {e}")
            return False

    def read_html(self, doc_id: str) -> Optional[str]:
        """Read HTML content"""
        try:
            file_path = self.config.htmls_path / f"{doc_id}.html"
            if not file_path.exists():
                self.logger.debug(f"HTML not found: {file_path}")
                return None
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            self.logger.error(f"Failed to read HTML {doc_id}: {e}")
            return None

    def delete_html(self, doc_id: str) -> bool:
        """Delete HTML file"""
        try:
            file_path = self.config.htmls_path / f"{doc_id}.html"
            if file_path.exists():
                file_path.unlink()
                self.logger.debug(f"Deleted HTML: {file_path}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Failed to delete HTML {doc_id}: {e}")
            return False

    def html_exists(self, doc_id: str) -> bool:
        """Check if HTML file exists"""
        return (self.config.htmls_path / f"{doc_id}.html").exists()

    # ==================== PDF Operations ====================

    def save_pdf(self, doc_id: str, content: bytes) -> bool:
        """Save PDF content"""
        try:
            file_path = self.config.pdfs_path / f"{doc_id}.pdf"
            with open(file_path, 'wb') as f:
                f.write(content)
            self.logger.debug(f"Saved PDF: {file_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save PDF {doc_id}: {e}")
            return False

    def read_pdf(self, doc_id: str) -> Optional[bytes]:
        """Read PDF content"""
        try:
            file_path = self.config.pdfs_path / f"{doc_id}.pdf"
            if not file_path.exists():
                self.logger.debug(f"PDF not found: {file_path}")
                return None
            with open(file_path, 'rb') as f:
                return f.read()
        except Exception as e:
            self.logger.error(f"Failed to read PDF {doc_id}: {e}")
            return None

    def delete_pdf(self, doc_id: str) -> bool:
        """Delete PDF file"""
        try:
            file_path = self.config.pdfs_path / f"{doc_id}.pdf"
            if file_path.exists():
                file_path.unlink()
                self.logger.debug(f"Deleted PDF: {file_path}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Failed to delete PDF {doc_id}: {e}")
            return False

    def pdf_exists(self, doc_id: str) -> bool:
        """Check if PDF file exists"""
        return (self.config.pdfs_path / f"{doc_id}.pdf").exists()

    def get_pdf_path(self, doc_id: str) -> Optional[str]:
        """Get the absolute path to PDF file"""
        file_path = self.config.pdfs_path / f"{doc_id}.pdf"
        if file_path.exists():
            return str(file_path.absolute())
        return None

    # ==================== Image Operations ====================

    def _get_image_dir(self, doc_id: str) -> Path:
        """Get the image directory for a paper (organized by doc_id)"""
        return self.config.imgs_path / doc_id

    def save_image(self, doc_id: str, image_id: str, content: bytes) -> bool:
        """Save image content"""
        try:
            img_dir = self._get_image_dir(doc_id)
            img_dir.mkdir(parents=True, exist_ok=True)
            file_path = img_dir / image_id
            with open(file_path, 'wb') as f:
                f.write(content)
            self.logger.debug(f"Saved image: {file_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save image {doc_id}/{image_id}: {e}")
            return False

    def read_image(self, doc_id: str, image_id: str) -> Optional[bytes]:
        """Read image content"""
        try:
            file_path = self._get_image_dir(doc_id) / image_id
            if not file_path.exists():
                file_path = self.config.imgs_path / image_id
                if not file_path.exists():
                    self.logger.debug(f"Image not found: {doc_id}/{image_id}")
                    return None
            with open(file_path, 'rb') as f:
                return f.read()
        except Exception as e:
            self.logger.error(f"Failed to read image {doc_id}/{image_id}: {e}")
            return None

    def delete_image(self, doc_id: str, image_id: str) -> bool:
        """Delete image file"""
        try:
            file_path = self._get_image_dir(doc_id) / image_id
            if file_path.exists():
                file_path.unlink()
                self.logger.debug(f"Deleted image: {file_path}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Failed to delete image {doc_id}/{image_id}: {e}")
            return False

    def image_exists(self, doc_id: str, image_id: str) -> bool:
        """Check if image exists"""
        file_path = self._get_image_dir(doc_id) / image_id
        if file_path.exists():
            return True
        return (self.config.imgs_path / image_id).exists()

    def list_images(self, doc_id: str) -> List[str]:
        """List all image IDs for a paper"""
        img_dir = self._get_image_dir(doc_id)
        if img_dir.exists():
            return [f.name for f in img_dir.iterdir() if f.is_file()]
        return []

    def get_image_path(self, doc_id: str, image_id: str) -> Optional[str]:
        """Get the path to image file"""
        file_path = self._get_image_dir(doc_id) / image_id
        if file_path.exists():
            return str(file_path.absolute())
        file_path = self.config.imgs_path / image_id
        if file_path.exists():
            return str(file_path.absolute())
        return None

    # ==================== Bulk Operations ====================

    def cleanup_paper_files(self, doc_id: str,
                           delete_blog: bool = False,
                           delete_json: bool = False,
                           delete_html: bool = False,
                           delete_pdf: bool = False,
                           delete_images: bool = False) -> Dict[str, bool]:
        """Clean up files for a specific paper based on flags."""
        results = {}
        if delete_blog:
            results['blog'] = self.delete_blog(doc_id)
        if delete_json:
            results['json'] = self.delete_paper_json(doc_id)
        if delete_html:
            results['html'] = self.delete_html(doc_id)
        if delete_pdf:
            results['pdf'] = self.delete_pdf(doc_id)
        if delete_images:
            img_dir = self._get_image_dir(doc_id)
            if img_dir.exists():
                shutil.rmtree(img_dir)
                results['images'] = True
            else:
                results['images'] = False
        return results

    def cleanup_all(self,
                   delete_blogs: bool = False,
                   delete_jsons: bool = False,
                   delete_htmls: bool = False,
                   delete_pdfs: bool = False,
                   delete_images: bool = False) -> Dict[str, int]:
        """Clean up all files based on flags."""
        results = {
            'blogs': 0,
            'jsons': 0,
            'htmls': 0,
            'pdfs': 0,
            'images': 0
        }

        if delete_blogs:
            for f in self.config.blogs_path.glob("*.md"):
                f.unlink()
                results['blogs'] += 1

        if delete_jsons:
            for f in self.config.jsons_path.glob("*.json"):
                f.unlink()
                results['jsons'] += 1

        if delete_htmls:
            for f in self.config.htmls_path.glob("*.html"):
                f.unlink()
                results['htmls'] += 1

        if delete_pdfs:
            for f in self.config.pdfs_path.glob("*.pdf"):
                f.unlink()
                results['pdfs'] += 1

        if delete_images:
            for item in self.config.imgs_path.iterdir():
                if item.is_file():
                    item.unlink()
                    results['images'] += 1
                elif item.is_dir():
                    for f in item.iterdir():
                        if f.is_file():
                            f.unlink()
                            results['images'] += 1
                    try:
                        item.rmdir()
                    except OSError:
                        pass

        self.logger.info(f"Cleaned up all files: {results}")
        return results

    def get_storage_stats(self) -> Dict[str, Any]:
        """Get statistics about stored files."""
        stats = {}

        blogs = list(self.config.blogs_path.glob("*.md"))
        stats['blogs'] = {
            'count': len(blogs),
            'total_size': sum(f.stat().st_size for f in blogs)
        }

        jsons = list(self.config.jsons_path.glob("*.json"))
        stats['jsons'] = {
            'count': len(jsons),
            'total_size': sum(f.stat().st_size for f in jsons)
        }

        htmls = list(self.config.htmls_path.glob("*.html"))
        stats['htmls'] = {
            'count': len(htmls),
            'total_size': sum(f.stat().st_size for f in htmls)
        }

        pdfs = list(self.config.pdfs_path.glob("*.pdf"))
        stats['pdfs'] = {
            'count': len(pdfs),
            'total_size': sum(f.stat().st_size for f in pdfs)
        }

        img_count = 0
        img_size = 0
        for item in self.config.imgs_path.rglob("*"):
            if item.is_file():
                img_count += 1
                img_size += item.stat().st_size
        stats['images'] = {
            'count': img_count,
            'total_size': img_size
        }

        return stats


def create_local_storage_manager(base_dir: str, **kwargs) -> LocalStorageManager:
    """Factory function to create a LocalStorageManager with default or custom paths."""
    config = StorageConfig(base_dir=base_dir, **kwargs)
    return LocalStorageManager(config)


# ==================== DashScope Embedding Client ====================

class EmbeddingClient:
    """DashScope Embedding client for generating text vector representations."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: str = "text-embedding-v4",
        dimension: int = 2048
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.dimension = dimension
        self.logger = logging.getLogger(self.__class__.__name__)

    def get_embedding(self, text: str) -> Optional[List[float]]:
        """Get embedding for a single text."""
        if not text or not text.strip():
            self.logger.warning("Empty text provided for embedding")
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
            embedding = result.get("data", [{}])[0].get("embedding")

            if embedding:
                self.logger.debug(f"Generated embedding with dimension {len(embedding)}")
                return embedding
            else:
                self.logger.error(f"No embedding in response: {result}")
                return None

        except httpx.HTTPStatusError as e:
            self.logger.error(f"HTTP error getting embedding: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            self.logger.error(f"Error getting embedding: {e}")
            return None

    def get_embeddings(
        self,
        texts: List[str],
        batch_size: int = 10,
        delay: float = 0.5
    ) -> List[Optional[List[float]]]:
        """Batch get embeddings for multiple texts."""
        embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            batch_embeddings = []

            for text in batch:
                embedding = self.get_embedding(text)
                batch_embeddings.append(embedding)

            embeddings.extend(batch_embeddings)

            # Delay between batches to avoid rate limiting
            if i + batch_size < len(texts):
                time.sleep(delay)

        success_count = sum(1 for e in embeddings if e is not None)
        self.logger.info(f"Generated {success_count}/{len(texts)} embeddings successfully")

        return embeddings


# ==================== Aliyun RDS Configuration ====================

@dataclass
class RDSConfig:
    """Aliyun RDS configuration"""
    host: str = "localhost"
    port: int = 5432
    database: str = "paperignition"
    user: str = "postgres"
    password: str = ""
    sslmode: str = "prefer"

    def get_connection_string(self) -> str:
        """Get PostgreSQL connection string"""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}?sslmode={self.sslmode}"


# ==================== RDS Database Manager ====================

class RDSDBManager:
    """
    Aliyun RDS Database Manager

    Provides CRUD operations for paper metadata, text chunks, and vector embeddings.
    Uses psycopg2 for synchronous database operations.
    """

    def __init__(self, config: RDSConfig, embedding_client: Optional[EmbeddingClient] = None):
        self.config = config
        self.embedding_client = embedding_client
        self._connection = None
        self.logger = logging.getLogger(self.__class__.__name__)

    def _get_connection(self):
        """Get database connection"""
        if self._connection is None or self._connection.closed:
            try:
                self._connection = psycopg2.connect(
                    host=self.config.host,
                    port=self.config.port,
                    database=self.config.database,
                    user=self.config.user,
                    password=self.config.password,
                    sslmode=self.config.sslmode
                )
                self.logger.debug(f"Connected to RDS: {self.config.host}:{self.config.port}/{self.config.database}")
            except Exception as e:
                self.logger.error(f"Failed to connect to RDS: {e}")
                raise
        return self._connection

    # Alias for backward compatibility
    get_connection = _get_connection

    def close(self):
        """Close database connection"""
        if self._connection and not self._connection.closed:
            self._connection.close()
            self.logger.debug("RDS connection closed")

    # ==================== Paper Metadata Operations ====================

    def insert_paper(self, paper) -> Optional[bool]:
        """Insert paper metadata into papers table. Skips if doc_id already exists.

        Returns:
            True if a new paper was inserted, False if it already existed, None on error.
        """
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                # Check if paper already exists
                cur.execute("SELECT 1 FROM papers WHERE doc_id = %s", (paper.doc_id,))
                if cur.fetchone():
                    self.logger.debug(f"Paper already exists, skipping: {paper.doc_id}")
                    return False

                # Reset sequence to avoid PK conflicts
                cur.execute("SELECT setval('papers_id_seq', COALESCE((SELECT MAX(id) FROM papers), 0) + 1, false)")

                cur.execute("""
                    INSERT INTO papers (doc_id, title, authors, abstract, categories, published_date, pdf_path, "HTML_path")
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    paper.doc_id,
                    paper.title,
                    json.dumps(paper.authors) if isinstance(paper.authors, list) else json.dumps([]),
                    paper.abstract,
                    json.dumps(paper.categories) if isinstance(paper.categories, list) else json.dumps([]),
                    paper.published_date,
                    getattr(paper, 'pdf_path', None),
                    getattr(paper, 'html_path', None)
                ))
                conn.commit()
                self.logger.debug(f"Inserted paper: {paper.doc_id}")
                return True
        except Exception as e:
            self.logger.error(f"Failed to insert paper {paper.doc_id}: {e}")
            if conn:
                conn.rollback()
            return False

    def update_paper_blog(self, doc_id: str, blog_content: str) -> bool:
        """Update paper blog content."""
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE papers
                    SET blog = %s
                    WHERE doc_id = %s
                """, (blog_content, doc_id))
                conn.commit()
                self.logger.debug(f"Updated blog for paper: {doc_id}")
                return True
        except Exception as e:
            self.logger.error(f"Failed to update blog for {doc_id}: {e}")
            if conn:
                conn.rollback()
            return False

    def get_all_doc_ids(self) -> set:
        """Return the set of all doc_ids currently stored in the papers table."""
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT doc_id FROM papers")
                return {row[0] for row in cur.fetchall()}
        except Exception as e:
            self.logger.error(f"Failed to fetch doc_ids: {e}")
            return set()

    def get_paper(self, doc_id: str) -> Optional[Dict]:
        """Get paper metadata."""
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT doc_id, title, authors, abstract, categories, published_date, pdf_path, "HTML_path", blog
                    FROM papers WHERE doc_id = %s
                """, (doc_id,))
                row = cur.fetchone()
                if row:
                    return {
                        "doc_id": row[0],
                        "title": row[1],
                        "authors": row[2],
                        "abstract": row[3],
                        "categories": row[4],
                        "published_date": row[5],
                        "pdf_path": row[6],
                        "html_path": row[7],
                        "blog": row[8]
                    }
                return None
        except Exception as e:
            self.logger.error(f"Failed to get paper {doc_id}: {e}")
            return None

    def get_paper_blog(self, doc_id: str) -> Optional[str]:
        """Get paper blog content."""
        paper = self.get_paper(doc_id)
        if paper:
            return paper.get("blog")
        return None

    def batch_update_papers_blog(self, papers_data: List[Dict[str, str]]) -> Tuple[int, int]:
        """Batch update paper blog content."""
        success_count = 0
        failed_count = 0

        for paper_data in papers_data:
            paper_id = paper_data.get("paper_id")
            blog_content = paper_data.get("blog_content")

            if paper_id and blog_content:
                if self.update_paper_blog(paper_id, blog_content):
                    success_count += 1
                else:
                    failed_count += 1
            else:
                failed_count += 1

        self.logger.info(f"Batch update blog: {success_count} succeeded, {failed_count} failed")
        return success_count, failed_count

    # ==================== Text Chunk Operations ====================

    def insert_text_chunks(self, doc_id: str, chunks: list) -> int:
        """Insert text chunks into text_chunks table."""
        if not chunks:
            return 0

        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute("DELETE FROM text_chunks WHERE doc_id = %s", (doc_id,))

                for i, chunk in enumerate(chunks):
                    chunk_id = getattr(chunk, 'id', f"{doc_id}_chunk_{i}")
                    text_content = getattr(chunk, 'text', '')
                    cur.execute("""
                        INSERT INTO text_chunks (id, doc_id, chunk_id, text_content, chunk_order, created_at)
                        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    """, (chunk_id, doc_id, chunk_id, text_content, i))

                conn.commit()
                self.logger.debug(f"Inserted {len(chunks)} text chunks for paper: {doc_id}")
                return len(chunks)
        except Exception as e:
            self.logger.error(f"Failed to insert text chunks for {doc_id}: {e}")
            if conn:
                conn.rollback()
            return 0

    # ==================== Embedding Operations ====================

    def insert_embedding(self, doc_id: str, title: str, abstract: str, embedding: List[float]) -> bool:
        """Insert or update paper vector embedding."""
        conn = None
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                embedding_str = str(embedding).replace('[', '[').replace(']', ']')

                cur.execute("""
                    INSERT INTO paper_embeddings (doc_id, title, abstract, embedding, updated_at)
                    VALUES (%s, %s, %s, %s::vector, CURRENT_TIMESTAMP)
                    ON CONFLICT (doc_id)
                    DO UPDATE SET
                        title = EXCLUDED.title,
                        abstract = EXCLUDED.abstract,
                        embedding = EXCLUDED.embedding,
                        updated_at = CURRENT_TIMESTAMP
                """, (doc_id, title, abstract, embedding_str))
                conn.commit()
                self.logger.debug(f"Inserted/updated embedding for paper: {doc_id}")
                return True
        except Exception as e:
            self.logger.error(f"Failed to insert embedding for {doc_id}: {e}")
            if conn:
                conn.rollback()
            return False

    def batch_insert_embeddings(
        self,
        papers: List[Dict],
        embeddings: List[Optional[List[float]]]
    ) -> Tuple[int, int]:
        """Batch insert vector embeddings."""
        success_count = 0
        failed_count = 0

        for paper, embedding in zip(papers, embeddings):
            if embedding is None:
                failed_count += 1
                continue

            if self.insert_embedding(
                doc_id=paper["doc_id"],
                title=paper["title"],
                abstract=paper["abstract"],
                embedding=embedding
            ):
                success_count += 1
            else:
                failed_count += 1

        self.logger.info(f"Batch insert embeddings: {success_count} succeeded, {failed_count} failed")
        return success_count, failed_count

    # ==================== Vector Search Operations ====================

    def find_similar_papers(
        self,
        query_embedding: List[float],
        top_k: int = 10,
        similarity_cutoff: float = 0.1,
        filters: Optional[Dict] = None
    ) -> List[Dict]:
        """Find similar papers using pgvector cosine similarity search."""
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                embedding_str = str(query_embedding).replace('[', '[').replace(']', ']')

                sql = """
                    SELECT pe.doc_id, pe.title, pe.abstract,
                           p.authors, p.categories, p.published_date,
                           1 - (pe.embedding <=> %s::vector) as similarity
                    FROM paper_embeddings pe
                    LEFT JOIN papers p ON pe.doc_id = p.doc_id
                    WHERE 1 - (pe.embedding <=> %s::vector) >= %s
                """
                params = [embedding_str, embedding_str, similarity_cutoff]

                if filters:
                    if "exclude" in filters and "doc_ids" in filters["exclude"]:
                        exclude_ids = filters["exclude"]["doc_ids"]
                        if exclude_ids:
                            placeholders = ",".join(["%s"] * len(exclude_ids))
                            sql += f" AND pe.doc_id NOT IN ({placeholders})"
                            params.extend(exclude_ids)

                    if "include" in filters and "published_date" in filters["include"]:
                        date_range = filters["include"]["published_date"]
                        if len(date_range) == 2:
                            sql += " AND p.published_date BETWEEN %s AND %s"
                            params.extend(date_range)

                sql += " ORDER BY pe.embedding <=> %s::vector LIMIT %s"
                params.extend([embedding_str, top_k])

                cur.execute(sql, params)
                rows = cur.fetchall()

                results = []
                for row in rows:
                    results.append({
                        "doc_id": row[0],
                        "title": row[1],
                        "abstract": row[2],
                        "authors": row[3] or [],
                        "categories": row[4] or [],
                        "published_date": str(row[5]) if row[5] else None,
                        "similarity": float(row[6])
                    })

                self.logger.info(f"Found {len(results)} similar papers (cutoff={similarity_cutoff})")
                return results

        except Exception as e:
            self.logger.error(f"Failed to find similar papers: {e}")
            return []

    def get_embedding_stats(self) -> Dict[str, Any]:
        """Get embedding table statistics."""
        try:
            conn = self._get_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM paper_embeddings")
                count = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM paper_embeddings WHERE updated_at > CURRENT_DATE")
                today_count = cur.fetchone()[0]

                return {
                    "total_embeddings": count,
                    "today_embeddings": today_count
                }
        except Exception as e:
            self.logger.error(f"Failed to get embedding stats: {e}")
            return {"total_embeddings": 0, "today_embeddings": 0}


# ==================== Aliyun OSS Configuration ====================

@dataclass
class AliyunOSSConfig:
    """Aliyun OSS configuration"""
    access_key_id: str
    access_key_secret: str
    endpoint: str
    bucket_name: str
    upload_prefix: str = "imgs/"

    def get_endpoint_url(self) -> str:
        """Get full endpoint URL"""
        if self.endpoint.startswith("http"):
            return self.endpoint
        return f"https://{self.endpoint}"


# ==================== Aliyun OSS Storage Manager ====================

class AliyunOSSStorageManager(StorageManager):
    """
    Aliyun OSS Storage Manager

    Inherits from StorageManager, implements OSS storage backend.
    Primarily used for image storage.
    """

    def __init__(self, storage_config: StorageConfig, oss_config: AliyunOSSConfig):
        super().__init__(storage_config)
        self.oss_config = oss_config
        self._bucket = None
        self._oss_enabled = False

        try:
            import oss2
            auth = oss2.Auth(oss_config.access_key_id, oss_config.access_key_secret)
            self._bucket = oss2.Bucket(
                auth,
                oss_config.endpoint,
                oss_config.bucket_name
            )
            self._oss_enabled = True
            self.logger.info(f"OSS Storage Manager initialized: {oss_config.bucket_name}")
        except ImportError:
            self.logger.warning("oss2 library not installed, OSS operations will fall back to local storage")
        except Exception as e:
            self.logger.error(f"Failed to initialize OSS client: {e}")

    def _get_oss_key(self, doc_id: str, image_id: str) -> str:
        """Get full OSS object key"""
        return f"{self.oss_config.upload_prefix}{doc_id}/{image_id}"

    def upload_image(self, doc_id: str, image_id: str, content: bytes) -> bool:
        """Upload image to OSS"""
        if not self._oss_enabled:
            self.logger.warning("OSS not enabled, falling back to local storage")
            return self.save_image(doc_id, image_id, content)

        try:
            key = self._get_oss_key(doc_id, image_id)
            self._bucket.put_object(key, content)
            self.logger.debug(f"Uploaded image to OSS: {key}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to upload image {doc_id}/{image_id} to OSS: {e}")
            return self.save_image(doc_id, image_id, content)

    def upload_images_from_docset(self, paper) -> Dict[str, bool]:
        """Upload all images from a DocSet to OSS."""
        import os as os_module
        results = {}

        figure_chunks = getattr(paper, 'figure_chunks', [])
        if not figure_chunks:
            return results

        for fig in figure_chunks:
            image_path = getattr(fig, 'image_path', None)
            if image_path:
                filename = os_module.path.basename(image_path)
            else:
                image_id = getattr(fig, 'id', f"fig_{len(results)}")
                filename = f"{paper.doc_id}_{image_id}.png"

            content = getattr(fig, 'image_data', None) or getattr(fig, 'content', None)

            if not content and image_path:
                try:
                    with open(image_path, 'rb') as f:
                        content = f.read()
                except Exception as e:
                    self.logger.warning(f"Failed to read image from {image_path}: {e}")
                    continue

            if content:
                if isinstance(content, str):
                    import base64
                    try:
                        content = base64.b64decode(content)
                    except Exception:
                        continue

                success = self.upload_image_by_filename(filename, content)
                results[filename] = success

        success_count = sum(1 for v in results.values() if v)
        self.logger.info(f"Uploaded {success_count}/{len(results)} images for paper {paper.doc_id}")
        return results

    def upload_image_by_filename(self, filename: str, content: bytes) -> bool:
        """Upload image to OSS using filename (no subdirectory)."""
        if not self._oss_enabled:
            self.logger.warning("OSS not enabled, falling back to local storage")
            return False

        try:
            key = f"{self.oss_config.upload_prefix}{filename}"
            self._bucket.put_object(key, content)
            self.logger.debug(f"Uploaded image to OSS: {key}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to upload image {filename} to OSS: {e}")
            return False

    # ==================== StorageManager abstract method implementations ====================

    def save_image(self, doc_id: str, image_id: str, content: bytes) -> bool:
        return LocalStorageManager.save_image(self, doc_id, image_id, content)

    def read_image(self, doc_id: str, image_id: str) -> Optional[bytes]:
        if self._oss_enabled:
            try:
                key = self._get_oss_key(doc_id, image_id)
                result = self._bucket.get_object(key)
                return result.read()
            except Exception as e:
                self.logger.debug(f"Image not found in OSS, trying local: {e}")
        return LocalStorageManager.read_image(self, doc_id, image_id)

    def delete_image(self, doc_id: str, image_id: str) -> bool:
        success = True
        if self._oss_enabled:
            try:
                key = self._get_oss_key(doc_id, image_id)
                self._bucket.delete_object(key)
            except Exception as e:
                self.logger.warning(f"Failed to delete from OSS: {e}")
                success = False
        local_success = LocalStorageManager.delete_image(self, doc_id, image_id)
        return success or local_success

    def image_exists(self, doc_id: str, image_id: str) -> bool:
        if self._oss_enabled:
            try:
                key = self._get_oss_key(doc_id, image_id)
                return self._bucket.object_exists(key)
            except Exception:
                pass
        return LocalStorageManager.image_exists(self, doc_id, image_id)

    def list_images(self, doc_id: str) -> List[str]:
        images = set()
        if self._oss_enabled:
            try:
                import oss2
                prefix = f"{self.oss_config.upload_prefix}{doc_id}/"
                for obj in oss2.ObjectIterator(self._bucket, prefix=prefix):
                    image_id = obj.key.split("/")[-1]
                    if image_id:
                        images.add(image_id)
            except Exception as e:
                self.logger.warning(f"Failed to list OSS images: {e}")
        local_images = LocalStorageManager.list_images(self, doc_id)
        images.update(local_images)
        return list(images)

    def get_image_path(self, doc_id: str, image_id: str) -> Optional[str]:
        return LocalStorageManager.get_image_path(self, doc_id, image_id)

    # Delegate non-image operations to local storage
    def save_blog(self, doc_id: str, content: str) -> bool:
        return LocalStorageManager.save_blog(self, doc_id, content)

    def read_blog(self, doc_id: str) -> Optional[str]:
        return LocalStorageManager.read_blog(self, doc_id)

    def delete_blog(self, doc_id: str) -> bool:
        return LocalStorageManager.delete_blog(self, doc_id)

    def blog_exists(self, doc_id: str) -> bool:
        return LocalStorageManager.blog_exists(self, doc_id)

    def list_blogs(self) -> List[str]:
        return LocalStorageManager.list_blogs(self)

    def save_paper_json(self, doc_id: str, data: Dict[str, Any]) -> bool:
        return LocalStorageManager.save_paper_json(self, doc_id, data)

    def read_paper_json(self, doc_id: str) -> Optional[Dict[str, Any]]:
        return LocalStorageManager.read_paper_json(self, doc_id)

    def delete_paper_json(self, doc_id: str) -> bool:
        return LocalStorageManager.delete_paper_json(self, doc_id)

    def paper_json_exists(self, doc_id: str) -> bool:
        return LocalStorageManager.paper_json_exists(self, doc_id)

    def list_paper_jsons(self) -> List[str]:
        return LocalStorageManager.list_paper_jsons(self)

    def save_html(self, doc_id: str, content: str) -> bool:
        return LocalStorageManager.save_html(self, doc_id, content)

    def read_html(self, doc_id: str) -> Optional[str]:
        return LocalStorageManager.read_html(self, doc_id)

    def delete_html(self, doc_id: str) -> bool:
        return LocalStorageManager.delete_html(self, doc_id)

    def html_exists(self, doc_id: str) -> bool:
        return LocalStorageManager.html_exists(self, doc_id)

    def save_pdf(self, doc_id: str, content: bytes) -> bool:
        return LocalStorageManager.save_pdf(self, doc_id, content)

    def read_pdf(self, doc_id: str) -> Optional[bytes]:
        return LocalStorageManager.read_pdf(self, doc_id)

    def delete_pdf(self, doc_id: str) -> bool:
        return LocalStorageManager.delete_pdf(self, doc_id)

    def pdf_exists(self, doc_id: str) -> bool:
        return LocalStorageManager.pdf_exists(self, doc_id)

    def get_pdf_path(self, doc_id: str) -> Optional[str]:
        return LocalStorageManager.get_pdf_path(self, doc_id)

    def cleanup_paper_files(self, doc_id: str, **kwargs) -> Dict[str, bool]:
        return LocalStorageManager.cleanup_paper_files(self, doc_id, **kwargs)

    def cleanup_all(self, **kwargs) -> Dict[str, int]:
        return LocalStorageManager.cleanup_all(self, **kwargs)


# ==================== Factory Functions ====================

def create_rds_db_manager(
    rds_config: Dict[str, Any],
    embedding_config: Optional[Dict[str, Any]] = None
) -> RDSDBManager:
    """Factory function to create an RDS database manager."""
    config = RDSConfig(
        host=rds_config.get("db_host", "localhost"),
        port=int(rds_config.get("db_port", 5432)),
        database=rds_config.get("db_name_paper", "paperignition"),
        user=rds_config.get("db_user", "postgres"),
        password=rds_config.get("db_password", ""),
        sslmode=rds_config.get("sslmode", "prefer")
    )

    embedding_client = None
    if embedding_config:
        embedding_client = EmbeddingClient(
            api_key=embedding_config.get("api_key", ""),
            base_url=embedding_config.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            model=embedding_config.get("embedding_model", "text-embedding-v4"),
            dimension=embedding_config.get("embedding_dimension", 2048)
        )

    return RDSDBManager(config, embedding_client)


def create_oss_storage_manager(
    base_dir: str,
    oss_config: Dict[str, Any],
    storage_options: Optional[Dict] = None
) -> AliyunOSSStorageManager:
    """Factory function to create an OSS storage manager."""
    storage_config = StorageConfig(base_dir=base_dir, **(storage_options or {}))

    oss_cfg = AliyunOSSConfig(
        access_key_id=oss_config.get("access_key_id", ""),
        access_key_secret=oss_config.get("access_key_secret", ""),
        endpoint=oss_config.get("endpoint", ""),
        bucket_name=oss_config.get("bucket_name", ""),
        upload_prefix=oss_config.get("upload_prefix", "imgs/")
    )

    return AliyunOSSStorageManager(storage_config, oss_cfg)
