"""Add last_login_at column and backfill from created_at.

Usage:
    # Against production (reads ~/paperignition/.env)
    python scripts/backfill_last_login.py

    # Dry run (print affected users without updating)
    python scripts/backfill_last_login.py --dry-run
"""
import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv("/Users/leahai/paperignition/.env")


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
        # 1. Drop is_active column
        print("Dropping is_active column...")
        if not dry_run:
            await conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS is_active"))
        print("  Done." if not dry_run else "  [DRY RUN] skipped.")

        # 2. Add last_login_at column if not exists
        print("Adding last_login_at column...")
        if not dry_run:
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP WITH TIME ZONE"
            ))
        print("  Done." if not dry_run else "  [DRY RUN] skipped.")

        if dry_run:
            print("\n[DRY RUN] Would backfill last_login_at = created_at for all NULL rows.")
            return

        # 3. Backfill: set last_login_at = created_at where NULL
        result = await conn.execute(text(
            "SELECT id, username, email, created_at FROM users WHERE last_login_at IS NULL"
        ))
        rows = result.fetchall()

        if not rows:
            print("No users need backfill.")
            return

        print(f"\n{len(rows)} users with NULL last_login_at:")
        for r in rows:
            print(f"  id={r[0]}  username={r[1]}  email={r[2]}  created_at={r[3]}")

        result = await conn.execute(text(
            "UPDATE users SET last_login_at = created_at WHERE last_login_at IS NULL"
        ))
        print(f"\nBackfilled {result.rowcount} users: last_login_at = created_at.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(migrate(dry_run=args.dry_run))
