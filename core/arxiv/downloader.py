"""Pure download utilities with retry logic. No arXiv-specific knowledge."""

import io
import logging
import os
import time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

_USER_AGENT = "Mozilla/5.0 (compatible; PaperIgnitionBot/2.0)"


def download_pdf(url: str, save_dir: Path | str, filename: str,
                 max_retries: int = 3) -> Path | None:
    """Download PDF with retry + verification. Returns path or None."""
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    final_path = save_dir / filename
    temp_path = save_dir / f"{filename}.tmp"

    session = requests.Session()
    retries = Retry(total=max_retries, backoff_factor=1,
                    status_forcelist=[500, 502, 503, 504])
    session.mount("http://", HTTPAdapter(max_retries=retries))
    session.mount("https://", HTTPAdapter(max_retries=retries))

    headers = {"User-Agent": _USER_AGENT, "Accept": "application/pdf"}

    try:
        response = session.get(url, headers=headers, stream=True, timeout=30)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0

        with open(temp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

        if total_size > 0 and downloaded != total_size:
            logger.warning("Size mismatch for %s: expected %d, got %d",
                           filename, total_size, downloaded)
            temp_path.unlink(missing_ok=True)
            return None

        if not verify_pdf(temp_path):
            temp_path.unlink(missing_ok=True)
            return None

        if final_path.exists():
            final_path.unlink()
        temp_path.rename(final_path)
        logger.info("Downloaded: %s", filename)
        return final_path

    except Exception as e:
        logger.error("Download failed %s: %s", filename, e)
        temp_path.unlink(missing_ok=True)
        return None


def download_pdf_arxiv(result, save_dir: Path | str, filename: str) -> Path | None:
    """Download paper PDF: try arxiv API first, then direct URL fallback.

    Args:
        result: arxiv.Result object
        save_dir: Directory to save the PDF
        filename: Filename for the PDF

    Returns:
        Path to downloaded PDF or None
    """
    save_dir = Path(save_dir)
    file_path = save_dir / filename

    # Attempt 1: arxiv API
    try:
        logger.info("Trying arxiv API download: %s", filename)
        result.download_pdf(dirpath=str(save_dir), filename=filename)
        if verify_pdf(file_path):
            logger.info("arxiv API download succeeded: %s", filename)
            return file_path
        else:
            logger.warning("arxiv API download produced invalid PDF, falling back")
            file_path.unlink(missing_ok=True)
    except Exception as e:
        logger.warning("arxiv API download failed: %s", e)
        file_path.unlink(missing_ok=True)

    # Attempt 2: direct URL
    pdf_url = result.entry_id.replace("abs", "pdf")
    return download_pdf(pdf_url, save_dir, filename)


def download_image(url: str, save_path: Path | str,
                   timeout: int = 15) -> bool:
    """Download image with retry. Returns success bool."""
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[502, 503, 504])
    session.mount("http://", HTTPAdapter(max_retries=retries))
    session.mount("https://", HTTPAdapter(max_retries=retries))

    headers = {"User-Agent": _USER_AGENT}
    time.sleep(1)  # Rate limit for arxiv

    try:
        response = session.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(response.content)
        logger.info("Downloaded image: %s", save_path.name)
        return True
    except Exception as e:
        logger.error("Image download failed %s: %s", url, e)
        return False


def get_image_from_url(arxiv_id: str, img_src: str) -> bytes | None:
    """Fetch image bytes from ar5iv HTML image source."""
    from urllib.parse import urljoin

    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[502, 503, 504])
    session.mount("http://", HTTPAdapter(max_retries=retries))
    session.mount("https://", HTTPAdapter(max_retries=retries))

    headers = {"User-Agent": _USER_AGENT}
    img_url = urljoin("https://arxiv.org/html/", img_src)
    time.sleep(1)

    try:
        response = session.get(img_url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.content
    except requests.exceptions.RequestException as e:
        logger.error("Failed to fetch image %s: %s", img_url, e)
        return None


def verify_pdf(path: Path | str) -> bool:
    """Check file is valid PDF (header check)."""
    try:
        with open(path, "rb") as f:
            header = f.read(5)
            if not header.startswith(b"%PDF-"):
                logger.warning("Invalid PDF header: %s", path)
                return False
        return True
    except Exception as e:
        logger.error("PDF verification failed %s: %s", path, e)
        return False


def compress_pdf(input_path: Path | str, max_size_mb: float = 7.5) -> Path:
    """Compress PDF to fit under size limit. Returns output path.

    Tries image re-encoding at decreasing quality, then page trimming as fallback.
    Overwrites the original file in-place.
    """
    import fitz  # PyMuPDF

    input_path = Path(input_path)
    original_size = input_path.stat().st_size
    max_bytes = max_size_mb * 1024 * 1024
    tmp_path = input_path.with_suffix(".compress_tmp")

    logger.info("Compressing PDF: %s (%.2f MB)", input_path.name,
                original_size / 1024 / 1024)

    # Try Pillow for image re-encoding
    try:
        from PIL import Image
        pillow_available = True
    except ImportError:
        pillow_available = False

    quality = 90
    step = 10
    out_buf = None
    size = None

    try:
        while quality >= 10:
            doc = fitz.open(str(input_path))

            if pillow_available:
                for page_idx in range(len(doc)):
                    page = doc[page_idx]
                    for img_info in page.get_images(full=True):
                        xref = img_info[0]
                        try:
                            img_dict = doc.extract_image(xref)
                            img_bytes = img_dict.get("image")
                            if not img_bytes:
                                continue
                            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                            buf = io.BytesIO()
                            img.save(buf, format="JPEG", quality=quality)
                            doc.update_image(xref, stream=buf.getvalue())
                        except Exception:
                            continue

            out_buf = io.BytesIO()
            doc.save(out_buf, garbage=4, deflate=True, clean=True, incremental=False)
            size = len(out_buf.getvalue())
            doc.close()

            logger.debug("Quality=%d -> %.2f MB", quality, size / 1024 / 1024)

            if size <= max_bytes:
                tmp_path.write_bytes(out_buf.getvalue())
                os.replace(str(tmp_path), str(input_path))
                logger.info("Compressed: %.2f MB -> %.2f MB (quality=%d)",
                            original_size / 1024 / 1024, size / 1024 / 1024, quality)
                return input_path

            quality -= step

        # Page trimming fallback
        logger.info("Trying page trimming...")
        orig_doc = fitz.open(str(input_path))
        total_pages = len(orig_doc)

        for keep in range(total_pages - 1, 0, -1):
            new_doc = fitz.open()
            new_doc.insert_pdf(orig_doc, from_page=0, to_page=keep - 1)

            if pillow_available:
                trim_quality = max(10, quality) if quality >= 10 else 30
                for page_idx in range(len(new_doc)):
                    for img_info in new_doc[page_idx].get_images(full=True):
                        xref = img_info[0]
                        try:
                            img_dict = new_doc.extract_image(xref)
                            img_bytes = img_dict.get("image")
                            if not img_bytes:
                                continue
                            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                            buf = io.BytesIO()
                            img.save(buf, format="JPEG", quality=trim_quality)
                            new_doc.update_image(xref, stream=buf.getvalue())
                        except Exception:
                            continue

            buf = io.BytesIO()
            new_doc.save(buf, garbage=4, deflate=True, clean=True, incremental=False)
            this_size = len(buf.getvalue())
            new_doc.close()

            if this_size <= max_bytes:
                tmp_path.write_bytes(buf.getvalue())
                os.replace(str(tmp_path), str(input_path))
                logger.info("Trimmed to %d pages: %.2f MB -> %.2f MB",
                            keep, original_size / 1024 / 1024, this_size / 1024 / 1024)
                orig_doc.close()
                return input_path

        orig_doc.close()

        # Could not meet target — save best effort
        if out_buf is not None:
            tmp_path.write_bytes(out_buf.getvalue())
            os.replace(str(tmp_path), str(input_path))
        logger.warning("Could not compress below %.1f MB, saved best effort", max_size_mb)
        return input_path

    finally:
        tmp_path.unlink(missing_ok=True)
