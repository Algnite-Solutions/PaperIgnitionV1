"""Redesigned arXiv extraction pipeline with clear separation of concerns."""

from .client import ArxivClient
from .downloader import compress_pdf, download_image, download_pdf, verify_pdf
from .html_extractor import HTMLExtractor
from .pdf_extractor import PDFExtractor

__all__ = [
    "ArxivClient",
    "HTMLExtractor",
    "PDFExtractor",
    "download_pdf",
    "download_image",
    "verify_pdf",
    "compress_pdf",
]
