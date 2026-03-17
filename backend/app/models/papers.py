from typing import List, Optional

from pydantic import BaseModel

from core.models import DocSet


class PaperBase(BaseModel):
    id: str
    title: str
    authors: str
    abstract: str
    url: Optional[str] = None
    submitted: Optional[str] = None
    recommendation_date: Optional[str] = None
    viewed: bool = False
    blog_liked: Optional[bool] = None

    @classmethod
    def from_docset(cls, docset: DocSet):
        return cls(
            id=docset.doc_id,
            title=docset.title,
            authors=", ".join(docset.authors),
            abstract=docset.abstract,
            url=docset.HTML_path
        )


class PaperDetail(PaperBase):
    markdownContent: str


class PaperRecommendation(BaseModel):
    id: Optional[int] = None
    username: str
    paper_id: str
    title: Optional[str] = None
    authors: Optional[str] = None
    abstract: Optional[str] = None
    url: Optional[str] = None
    content: Optional[str] = None
    blog: Optional[str] = None
    reason: Optional[str] = None
    recommendation_date: Optional[str] = None
    viewed: bool = False
    relevance_score: Optional[float] = None
    recommendation_reason: Optional[str] = None
    blog_title: Optional[str] = None
    blog_abs: Optional[str] = None
    submitted: Optional[str] = None
    comment: Optional[str] = None
    is_saved: bool = False
    blog_liked: Optional[bool] = None
    blog_feedback_date: Optional[str] = None


class FeedbackRequest(BaseModel):
    username: str
    blog_liked: Optional[bool] = None


class RetrieveResultSave(BaseModel):
    username: str
    query: str
    search_strategy: str
    recommendation_date: Optional[str] = None
    retrieve_ids: List[str]
    top_k_ids: List[str]


class RetrieveResultResponse(BaseModel):
    success: bool
    message: str
    id: Optional[int] = None
