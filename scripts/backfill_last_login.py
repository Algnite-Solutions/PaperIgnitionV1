"""Add last_login_at column and backfill from GREATEST(created_at, last viewed recommendation).

Safe to run anytime — only ADDs, never drops. Idempotent.

Usage:
    # Against production (reads .env for DB credentials)
    python scripts/backfill_last_login.py

    # Dry run (print affected users without updating)
    python scripts/backfill_last_login.py --dry-run
"""
import argparse
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()


async def migrate(dry_run: bool = False):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    db_user = os.environ["DB_USER"]
    db_password = os.environ["DB_PASSWORD"]
    db_host = os.environ["DB_HOST"]
    db_port = os.environ["DB_PORT"]
    db_name = os.environ["DB_NAME_USER"]

    url = f"postgresql+asyncpg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    engine = create_async_engine(url)

    async with engine.begin() as conn:
        # 1. Add last_login_at column if not exists (idempotent)
        print("Adding last_login_at column...")
        if not dry_run:
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP WITH TIME ZONE"
            ))
        print("  Done." if not dry_run else "  [DRY RUN] skipped.")

        if dry_run:
            print("\n[DRY RUN] Would backfill last_login_at = GREATEST(created_at, last viewed recommendation).")
            return

        # 2. Backfill: set last_login_at to the more recent of created_at or last viewed recommendation
        result = await conn.execute(text("""
            UPDATE users u
            SET last_login_at = GREATEST(
                u.created_at,
                COALESCE((
                    SELECT MAX(pr.recommendation_date)
                    FROM paper_recommendations pr
                    WHERE pr.username = u.username AND pr.viewed = true
                ), u.created_at)
            )
            WHERE u.last_login_at IS NULL
               OR u.last_login_at < COALESCE((
                    SELECT MAX(pr.recommendation_date)
                    FROM paper_recommendations pr
                    WHERE pr.username = u.username AND pr.viewed = true
                ), u.created_at)
        """))
        print(f"\nBackfilled {result.rowcount} users: last_login_at = GREATEST(created_at, last_viewed).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(migrate(dry_run=args.dry_run))
