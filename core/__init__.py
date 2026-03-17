"""Core library for PaperIgnition — replaces the AIgnite package dependency."""

from .generators import GeminiBlogGenerator_default, GeminiBlogGenerator_recommend
from .models import ChunkType, DocSet, FigureChunk, TableChunk, TextChunk
from .rerankers import GeminiReranker, GeminiRerankerPDF

__all__ = [
    "DocSet",
    "TextChunk",
    "FigureChunk",
    "TableChunk",
    "ChunkType",
    "GeminiBlogGenerator_default",
    "GeminiBlogGenerator_recommend",
    "GeminiReranker",
    "GeminiRerankerPDF",
]
