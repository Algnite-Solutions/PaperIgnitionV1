"""Data models for PaperIgnition documents and chunks."""

from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, Field


class ChunkType(str, Enum):
    TEXT = "text"
    FIGURE = "figure"
    TABLE = "table"


class BaseChunk(BaseModel):
    id: Optional[str] = None
    type: ChunkType
    title: Optional[str] = None
    caption: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class TextChunk(BaseChunk):
    type: Literal[ChunkType.TEXT] = ChunkType.TEXT
    chunk_id: str = ""
    text: str = ""
    chunk_order: int = 0


class FigureChunk(BaseChunk):
    type: Literal[ChunkType.FIGURE] = ChunkType.FIGURE
    image_path: Optional[str] = None
    alt_text: Optional[str] = None
    image_data: Optional[bytes] = None


class TableChunk(BaseChunk):
    type: Literal[ChunkType.TABLE] = ChunkType.TABLE
    table_html: Optional[str] = None


Chunk = Union[TextChunk, FigureChunk, TableChunk]


class DocSet(BaseModel):
    doc_id: Optional[str] = None
    title: str = ""
    authors: List[str] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    published_date: str = ""
    abstract: str = ""
    text_chunks: List[Chunk] = Field(default_factory=list)
    figure_chunks: List[Chunk] = Field(default_factory=list)
    table_chunks: List[Chunk] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    pdf_path: Optional[str] = None
    HTML_path: Optional[str] = None
    comments: Optional[str] = None


class DocSetList(BaseModel):
    docsets: List[DocSet]
