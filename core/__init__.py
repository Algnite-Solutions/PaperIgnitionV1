"""Core library for PaperIgnition — replaces the AIgnite package dependency."""

from .models import DocSet, TextChunk, FigureChunk, TableChunk, ChunkType
from .generators import GeminiBlogGenerator_default, GeminiBlogGenerator_recommend
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
