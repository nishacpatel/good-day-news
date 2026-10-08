"""Create (or update) the database tables in Supabase from db/schema.sql.

    python scripts/init_db.py
"""

import re

from gooddaynews.db import connect
from gooddaynews.settings import ROOT


def statements(sql: str) -> list[str]:
    sql = re.sub(r"--[^\n]*", "", sql)
    return [s.strip() for s in sql.split(";") if s.strip()]


def main() -> None:
    conn = connect()
    try:
        stmts = statements((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
        for stmt in stmts:
            conn.run(stmt)
        tables = conn.run("select table_name from information_schema.tables where table_schema = 'public' order by 1")
        print(f"Applied {len(stmts)} statements. Tables: {', '.join(t[0] for t in tables)}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
