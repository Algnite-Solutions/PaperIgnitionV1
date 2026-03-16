#!/usr/bin/env python3
"""Reset a user's password in the PaperIgnition database."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from backend.config_utils import load_config
from backend.app.auth.utils import get_password_hash


def reset_password(username: str, new_password: str, config_path: str = None):
    config = load_config(config_path)
    db_config = config.get("USER_DB", {})
    db_url = (
        f"postgresql+psycopg2://{db_config['db_user']}:{db_config['db_password']}"
        f"@{db_config['db_host']}:{db_config['db_port']}/{db_config['db_name']}"
    )
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        hashed = get_password_hash(new_password)
        result = session.execute(
            text("UPDATE users SET hashed_password = :pwd WHERE username = :username"),
            {"pwd": hashed, "username": username}
        )
        if result.rowcount == 0:
            print(f"User '{username}' not found")
            return False
        session.commit()
        print(f"Password reset successfully for user '{username}'")
        return True
    except Exception as e:
        session.rollback()
        print(f"Error: {e}")
        return False
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reset user password")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    success = reset_password(args.username, args.password, args.config)
    sys.exit(0 if success else 1)
