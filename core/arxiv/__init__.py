"""Redesigned arXiv extraction pipeline with clear separation of concerns."""

from .client import ArxivClient
from .html_extractor import HTMLExtractor
from .pdf_extractor import PDFExtractor
from .downloader import download_pdf, download_image, verify_pdf, compress_pdf

__all__ = [
    "ArxivClient",
    "HTMLExtractor",
    "PDFExtractor",
    "download_pdf",
    "download_image",
    "verify_pdf",
    "compress_pdf",
]
