"""After resetting the Supabase database password, save it as a pooler connection string in .env.

    .venv\\Scripts\\python scripts\\set_database_password.py

Asks only for the new password (hidden). The project and pooler host come from the current DATABASE_URL, so there
is no connection string to copy. Refuses to save the same password again, so a reset can't silently be skipped.
"""

import getpass
import re
import sys
from pathlib import Path
from urllib.parse import quote

import pg8000.native

from gooddaynews.db import parse_database_url, ssl_context
from gooddaynews.settings import get_settings

ENV = Path(__file__).resolve().parents[1] / ".env"
POOLER_HOST = "aws-0-ap-southeast-1.pooler.supabase.com"  # this project's region (found 9 Oct 2026)


def project_ref(current) -> str:
    direct = re.match(r"db\.([a-z0-9]+)\.supabase\.co$", current.host)
    if direct:
        return direct.group(1)
    if current.user.startswith("postgres."):
        return current.user.split(".", 1)[1]
    raise SystemExit("Can't tell the Supabase project from DATABASE_URL; use scripts/set_database_url.py instead.")


def main() -> int:
    current = parse_database_url(get_settings().database_url)
    ref = project_ref(current)
    password = getpass.getpass("New database password (hidden), then press Enter: ")
    if not password:
        print("Not saved: no password entered.")
        return 1
    if password == current.password:
        print("Not saved: this is the same password as before. Reset it in Supabase first "
              "(Project Settings > Database > Reset database password > Generate a password).")
        return 1
    user = f"postgres.{ref}"
    try:
        conn = pg8000.native.Connection(user=user, password=password, host=POOLER_HOST, port=5432,
                                        database="postgres", ssl_context=ssl_context(), timeout=20)
        conn.run("select 1")
        conn.close()
    except Exception as exc:
        print(f"Not saved: couldn't connect with that password ({type(exc).__name__}: "
              f"{str(exc).replace(password, '***')[:150]}). Was the reset saved in Supabase?")
        return 1
    url = f"postgresql://{user}:{quote(password, safe='')}@{POOLER_HOST}:5432/postgres"
    text = ENV.read_text(encoding="utf-8")
    text = re.sub(r"^DATABASE_URL=.*$", lambda _: f"DATABASE_URL={url}", text, count=1, flags=re.M)
    ENV.write_text(text, encoding="utf-8")
    print(f"Connected through the pooler and saved to {ENV}. The old password no longer matters.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
