"""
Run this once to add auth tables to existing database.
Usage: python auth/migrations.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_conn, USE_POSTGRES
from auth.models import ADD_AUTH_TABLES, ADD_AUTH_TABLES_SQLITE


def run_migration():
    print("Running auth migrations...")
    schema = ADD_AUTH_TABLES if USE_POSTGRES else ADD_AUTH_TABLES_SQLITE
    with get_conn() as conn:
        cur = conn.cursor()
        for stmt in schema.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)
    print("✓ Auth tables created successfully")
    print("  - users")
    print("  - sessions")


if __name__ == "__main__":
    run_migration()
