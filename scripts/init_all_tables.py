#!/usr/bin/env python3
"""
PaperIgnition v2 Database Initialization Script

Creates all database tables using raw SQL (no AIgnite dependency).
Supports two databases:
1. User DB (paperignition_user) - Users, recommendations, favorites
2. Paper DB (paperignition) - Papers, text chunks, embeddings
"""

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import sessionmaker

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.app.db_utils import Base as UserBase
from backend.app.models.users import (
    ProfilePoolEntry,
    ResearchDomain,
)
from backend.config_utils import load_config

# Research domain seed data
AI_DOMAINS = [
    {"name": "Natural Language Processing", "code": "NLP", "description": "NLP techniques including text analysis, generation, translation"},
    {"name": "Computer Vision", "code": "CV", "description": "Computer vision including image recognition, object detection"},
    {"name": "Large Language Models", "code": "LLM", "description": "Large language models and related research"},
    {"name": "Machine Learning", "code": "ML", "description": "General machine learning methods and techniques"},
    {"name": "Deep Learning", "code": "DL", "description": "Deep neural networks and related techniques"},
    {"name": "Reinforcement Learning", "code": "RL", "description": "Reinforcement learning algorithms and applications"},
    {"name": "Generative AI", "code": "GAI", "description": "Generative AI: GANs, diffusion models, etc."},
    {"name": "Multimodal Learning", "code": "MM", "description": "Multimodal learning combining different data types"},
    {"name": "Speech Recognition", "code": "ASR", "description": "Speech recognition and processing"},
    {"name": "Recommendation Systems", "code": "REC", "description": "Recommendation systems and personalization"},
    {"name": "Graph Neural Networks", "code": "GNN", "description": "Graph neural networks and graph data analysis"},
    {"name": "Federated Learning", "code": "FL", "description": "Federated learning and distributed AI"},
    {"name": "Knowledge Graphs", "code": "KG", "description": "Knowledge graphs and representation learning"},
]


def ensure_database_exists(database_url: str, default_database: str = "postgres"):
    """Ensure target database exists, create it if missing."""
    url = make_url(database_url)
    target_database = url.database
    if not target_database:
        raise ValueError(f"Invalid database URL, missing database name: {database_url}")

    admin_url = url.set(database=default_database)
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")

    try:
        with admin_engine.connect() as conn:
            try:
                conn.execute(text(f'CREATE DATABASE "{target_database}"'))
                print(f"Created database: {target_database}")
            except ProgrammingError as exc:
                if "already exists" in str(exc).lower():
                    print(f"Database already exists: {target_database}")
                else:
                    raise
    finally:
        admin_engine.dispose()


def init_user_database(config_path: str = None, drop_existing: bool = False):
    """Initialize user database tables using SQLAlchemy models."""
    print("\n" + "=" * 60)
    print("Initializing User Database")
    print("=" * 60)

    config = load_config(config_path)
    db_config = config.get("USER_DB", {})

    db_user = db_config.get("db_user", "postgres")
    db_password = db_config.get("db_password", "")
    db_host = db_config.get("db_host", "localhost")
    db_port = db_config.get("db_port", "5432")
    db_name = db_config.get("db_name", "paperignition_user")

    database_url = f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    ensure_database_exists(database_url)

    engine = create_engine(database_url)
    try:
        if drop_existing:
            UserBase.metadata.drop_all(engine)

        UserBase.metadata.create_all(engine)
        inspector = inspect(engine)
        print(f"Tables: {', '.join(inspector.get_table_names())}")

        # Create composite index and run migrations
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_username_date
                ON user_retrieve_results(username, recommendation_date)
            """))

            # Migration: add blog_language column if missing
            conn.execute(text("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS blog_language VARCHAR(10) DEFAULT 'zh'
            """))

            # Migration: email verification + password reset columns
            conn.execute(text("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verification_token VARCHAR(64)
            """))
            conn.execute(text("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verification_expires_at TIMESTAMP WITH TIME ZONE
            """))
            conn.execute(text("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_token VARCHAR(64)
            """))
            conn.execute(text("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_expires_at TIMESTAMP WITH TIME ZONE
            """))
            # Indexes for token lookups
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_users_email_verification_token
                ON users(email_verification_token)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS ix_users_password_reset_token
                ON users(password_reset_token)
            """))

            # Migration: profile pool optimization columns
            conn.execute(text("""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_pool_version INTEGER DEFAULT 0
            """))

            conn.commit()

        # Seed research domains
        Session = sessionmaker(bind=engine)
        session = Session()
        try:
            if session.query(ResearchDomain).count() == 0:
                for domain_data in AI_DOMAINS:
                    session.add(ResearchDomain(**domain_data))
                session.commit()
                print(f"Seeded {len(AI_DOMAINS)} research domains")
            else:
                print("Research domains already exist, skipping seed")
        except Exception as e:
            session.rollback()
            print(f"Failed to seed data: {e}")
        finally:
            session.close()

        print("User database initialized successfully")
    finally:
        engine.dispose()


def init_paper_database(config_path: str = None, drop_existing: bool = False):
    """Initialize paper metadata database using raw SQL (no AIgnite dependency)."""
    print("\n" + "=" * 60)
    print("Initializing Paper Metadata Database")
    print("=" * 60)

    config = load_config(config_path)
    rds_config = config.get("aliyun_rds", {})

    if not rds_config.get("enabled", False):
        # Fall back to USER_DB host with paperignition database
        db_config = config.get("USER_DB", {})
        db_user = db_config.get("db_user", "postgres")
        db_password = db_config.get("db_password", "")
        db_host = db_config.get("db_host", "localhost")
        db_port = db_config.get("db_port", "5432")
        db_name = "paperignition"
    else:
        db_user = rds_config.get("db_user", "postgres")
        db_password = rds_config.get("db_password", "")
        db_host = rds_config.get("db_host", "localhost")
        db_port = rds_config.get("db_port", "5432")
        db_name = rds_config.get("db_name_paper", "paperignition")

    database_url = f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    ensure_database_exists(database_url)

    engine = create_engine(database_url)
    try:
        with engine.connect() as conn:
            if drop_existing:
                conn.execute(text("DROP TABLE IF EXISTS text_chunks CASCADE"))
                conn.execute(text("DROP TABLE IF EXISTS paper_embeddings CASCADE"))
                conn.execute(text("DROP TABLE IF EXISTS papers CASCADE"))
                conn.commit()

            # Create papers table
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS papers (
                    id SERIAL PRIMARY KEY,
                    doc_id VARCHAR(100) UNIQUE NOT NULL,
                    title TEXT,
                    abstract TEXT,
                    authors JSONB,
                    categories JSONB,
                    published_date TIMESTAMP WITH TIME ZONE,
                    pdf_data BYTEA,
                    chunk_ids JSONB,
                    figure_ids JSONB,
                    image_storage JSONB,
                    table_ids JSONB,
                    extra_metadata JSONB,
                    pdf_path TEXT,
                    "HTML_path" TEXT,
                    blog TEXT,
                    comments TEXT
                )
            """))

            # Create text_chunks table
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS text_chunks (
                    id VARCHAR(200) PRIMARY KEY,
                    doc_id VARCHAR(100) NOT NULL,
                    chunk_id VARCHAR(100) NOT NULL,
                    text_content TEXT,
                    chunk_order INTEGER,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    UNIQUE(doc_id, chunk_id)
                )
            """))

            # Create paper_embeddings table (pgvector)
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS paper_embeddings (
                    id SERIAL PRIMARY KEY,
                    doc_id VARCHAR(100) UNIQUE NOT NULL,
                    title TEXT,
                    abstract TEXT,
                    embedding vector(1536)
                )
            """))

            # Create indexes
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_papers_doc_id ON papers(doc_id)"))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_papers_fts
                ON papers USING GIN (
                    to_tsvector('english', coalesce(title, '') || ' ' || coalesce(abstract, ''))
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_text_chunks_doc_id ON text_chunks(doc_id)"))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_text_chunks_fts
                ON text_chunks USING GIN (to_tsvector('english', coalesce(text_content, '')))
            """))

            # Create HNSW index for vector search
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_paper_embeddings_hnsw
                ON paper_embeddings USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 200)
            """))

            # Create full-text search ranking function
            conn.execute(text("""
                CREATE OR REPLACE FUNCTION fts_rank(
                    title text, abstract text, q tsquery,
                    title_weight float DEFAULT 0.7,
                    abstract_weight float DEFAULT 0.3
                ) RETURNS float AS $$
                BEGIN
                    RETURN (
                        title_weight * ts_rank_cd(
                            setweight(to_tsvector('english', coalesce(title, '')), 'A'), q
                        ) +
                        abstract_weight * ts_rank_cd(
                            setweight(to_tsvector('english', coalesce(abstract, '')), 'B'), q
                        )
                    );
                END;
                $$ LANGUAGE plpgsql
            """))

            conn.commit()

        inspector = inspect(engine)
        print(f"Tables: {', '.join(inspector.get_table_names())}")
        print("Paper database initialized successfully")

    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="PaperIgnition v2 Database Initialization")
    parser.add_argument("--config", type=str, default=None, help="Config file path")
    parser.add_argument("--drop", action="store_true", help="Drop existing tables before creating")
    parser.add_argument("--user-db-only", action="store_true", help="Initialize only user database")
    parser.add_argument("--paper-db-only", action="store_true", help="Initialize only paper database")
    args = parser.parse_args()

    config_path = args.config
    if config_path is None:
        local_mode = os.getenv("PAPERIGNITION_LOCAL_MODE", "false").lower() == "true"
        config_file = "ci_config.yaml" if local_mode else "app_config.yaml"
        config_path = str(project_root / "backend" / "configs" / config_file)

    if not os.path.exists(config_path):
        print(f"Config file not found: {config_path}")
        sys.exit(1)

    print(f"Using config: {config_path}")

    try:
        if not args.paper_db_only:
            init_user_database(config_path, drop_existing=args.drop)
        if not args.user_db_only:
            init_paper_database(config_path, drop_existing=args.drop)
        print("\nAll databases initialized successfully!")
    except Exception as e:
        print(f"\nInitialization failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
