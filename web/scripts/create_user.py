"""
Provision a user account for the Pancracio ideas tracker.

No self-service registration exists (deliberately — see
docs/ideation/pancracio-user-accounts/contract-data.json's decision log). This
script is the only way to create an account, run manually over SSH, matching
this project's existing SSH-based operational model (also used for password
reset — see internal-docs/ideas-tracker/deployment-runbook.md).

Usage (from web/):
    venv/bin/python3 scripts/create_user.py <username> <password>
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import _connect, hash_password  # noqa: E402


def main(username: str, password: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, hash_password(password)),
        )
    print(f"Created user: {username}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: create_user.py <username> <password>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
