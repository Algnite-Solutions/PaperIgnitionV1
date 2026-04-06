from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Table, Text
from sqlalchemy.dialects.postgresql import JSON, JSONB
from sqlalchemy.orm import relationship

from ..db_utils import Base

# 用户和研究领域的多对多关联表
user_domain_association = Table(
    'user_domain_association',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id'), primary_key=True),
    Column('domain_id', Integer, ForeignKey('research_domains.id'), primary_key=True)
)

class User(Base):
    """用户模型，存储用户基本信息"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True)
    email = Column(String(100), unique=True, index=True, nullable=True)
    hashed_password = Column(String(100), nullable=True)  # 为支持微信登录，密码可空

    # 微信相关字段
    wx_openid = Column(String(50), unique=True, index=True, nullable=True)
    wx_nickname = Column(String(50), nullable=True)
    wx_avatar_url = Column(String(255), nullable=True)
    wx_phone = Column(String(20), nullable=True)

    # 用户偏好
    push_frequency = Column(String(20), default="daily")  # daily, weekly

    # 元数据
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Email verification
    email_verification_token = Column(String(64), nullable=True, index=True)
    email_verification_expires_at = Column(DateTime(timezone=True), nullable=True)

    # Password reset
    password_reset_token = Column(String(64), nullable=True, index=True)
    password_reset_expires_at = Column(DateTime(timezone=True), nullable=True)
    # 关联关系
    profile_json = Column(JSONB, nullable=True)  # 用户的个性化配置文件结构
    research_interests_text = Column(Text, nullable=True)  # 用户主观研究兴趣描述文本
    rewrite_interest = Column(Text, nullable=True)  # LLM重写后的兴趣描述
    blog_language = Column(String(10), default="zh")  # Blog language preference: "zh" or "en"
    profile_boost_requested = Column(Boolean, default=False)  # User clicked "Boost My Profile"
    profile_last_extracted_at = Column(DateTime(timezone=True), nullable=True)  # Last profile extraction timestamp
    research_domains = relationship("ResearchDomain", secondary=user_domain_association, back_populates="users")
    favorite_papers = relationship("FavoritePaper", back_populates="user")
    recommended_papers = relationship("UserPaperRecommendation", back_populates="user")
    retrieve_results = relationship("UserRetrieveResult", back_populates="user")


class ResearchDomain(Base):
    """研究领域模型，存储AI领域分类"""
    __tablename__ = "research_domains"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True)
    code = Column(String(20), unique=True)  # 简短代码，如'NLP', 'CV'等
    description = Column(Text, nullable=True)

    # 关联关系
    users = relationship("User", secondary=user_domain_association, back_populates="research_domains")


class FavoritePaper(Base):
    """用户收藏的论文"""
    __tablename__ = "favorite_papers"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    paper_id = Column(String(50), primary_key=True)  # 论文外部ID (arXiv ID等)
    title = Column(String(255))
    authors = Column(String(255))
    abstract = Column(Text, nullable=True)
    url = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # 关联关系
    user = relationship("User", back_populates="favorite_papers")


class UserPaperRecommendation(Base):
    """
    只存储推荐关系，链表@Fang Guo的论文表与@Hui Chen的用户表，链表论文表的主键为paper_id，用户表的主键为user_id
    扩展字段：userid, paperid, title, authors, abstract, url, content, blog, reason
    """
    __tablename__ = "paper_recommendations"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), ForeignKey("users.username"), index=True)
    paper_id = Column(String(50), index=True)  # 论文外部ID (arXiv ID等)
    title = Column(String(255), nullable=True)
    authors = Column(String(255), nullable=True)
    abstract = Column(Text, nullable=True)
    url = Column(String(255), nullable=True)
    blog = Column(Text, nullable=True)
    blog_title = Column(Text, nullable=True)  # 博客标题
    blog_abs = Column(Text, nullable=True)    # 博客摘要
    recommendation_date = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    viewed = Column(Boolean, default=False)
    relevance_score = Column(Float, nullable=True)
    recommendation_reason = Column(Text, nullable=True)
    submitted = Column(String(255), nullable=True)  # 提交信息
    comment = Column(Text, nullable=True)  # 评论
    # 博客喜欢字段
    blog_liked = Column(Boolean, nullable=True)  # True=喜欢, False=不喜欢, None=未评价
    blog_feedback_date = Column(DateTime(timezone=True), nullable=True)  # 博客反馈时间
    # 关联关系
    user = relationship("User", back_populates="recommended_papers")


class UserRetrieveResult(Base):
    """用户检索结果记录表 - 用于 reranking 调试"""
    __tablename__ = "user_retrieve_results"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), ForeignKey("users.username"), index=True)
    query = Column(Text, nullable=False)  # 搜索关键词
    search_strategy = Column(String(50), nullable=False)  # vector/tf-idf/bm25
    recommendation_date = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # JSON 数组存储 paper IDs
    retrieve_ids = Column(JSON, nullable=False)  # Top retrieve_k 的 paper_ids
    top_k_ids = Column(JSON, nullable=False)     # Top k 的 paper_ids (subset)

    # 关联关系
    user = relationship("User", back_populates="retrieve_results")

    # 索引优化
    __table_args__ = (
        Index('idx_username_date', 'username', 'recommendation_date'),
    )


class JobLog(Base):
    """作业执行日志表"""
    __tablename__ = "job_logs"

    id = Column(Integer, primary_key=True, index=True)
    job_type = Column(String(100), nullable=False, index=True)  # e.g., "blog_generation", "paper_recommendation"
    job_id = Column(String(255), nullable=False, index=True)    # unique job identifier
    status = Column(String(50), nullable=False, index=True)     # "success", "failed", "partial", "running"

    # Job details
    username = Column(String(50), nullable=True, index=True)    # associated user if applicable

    # Timing
    start_time = Column(DateTime(timezone=True), nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Float, nullable=True)

    # Additional data
    error_message = Column(Text, nullable=True)                 # error details if failed
    details = Column(Text, nullable=True)                       # JSON string for additional details

    # Metadata
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
