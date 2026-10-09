"""Save a new DATABASE_URL into .env after checking it works. The value is typed hidden and never printed.

    .venv\\Scripts\\python scripts\\set_database_url.py
"""

import getpass
import re
import sys
from pathlib import Path

import pg8000.native

from gooddaynews.db import parse_database_url, ssl_context

ENV = Path(__file__).resolve().parents[1] / ".env"


def problems(url: str) -> list[str]:
    if "YOUR-PASSWORD" in url or "<password>" in url:
        return ["put your database password in place of [YOUR-PASSWORD]"]
    try:
        u = parse_database_url(url)
    except ValueError as exc:
        return [str(exc)]
    out = []
    if not u.host.endswith(".pooler.supabase.com"):
        out.append("the host should end in .pooler.supabase.com (choose 'Session pooler' in Supabase, not 'Direct')")
    if not u.user.startswith("postgres."):
        out.append("the user should look like postgres.<project-ref>")
    if not u.password:
        out.append("the password is missing")
    return out


def connects(url: str) -> str | None:
    u = parse_database_url(url)
    try:
        conn = pg8000.native.Connection(user=u.user, password=u.password, host=u.host, port=u.port,
                                        database=u.database, ssl_context=ssl_context(), timeout=20)
        conn.run("select 1")
        conn.close()
        return None
    except Exception as exc:
        return f"{type(exc).__name__}: {str(exc).replace(u.password, '***')[:200]}"


def main() -> int:
    url = getpass.getpass("Paste the Session pooler connection string (hidden), then press Enter: ").strip().strip('"')
    issues = problems(url)
    if issues:
        print("Not saved: " + "; ".join(issues) + ".")
        return 1
    error = connects(url)
    if error:
        print(f"Not saved: couldn't connect ({error}). Check the password and try again.")
        return 1
    text = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    line = f"DATABASE_URL={url}"
    if re.search(r"^DATABASE_URL=.*$", text, flags=re.M):
        text = re.sub(r"^DATABASE_URL=.*$", lambda _: line, text, count=1, flags=re.M)
    else:
        text = line + "\n" + text
    ENV.write_text(text, encoding="utf-8")
    print(f"Connected and saved to {ENV}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
