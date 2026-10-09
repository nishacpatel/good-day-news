"""Postgres connection (Supabase) using the pure-Python pg8000 driver."""

import os
import re
import ssl
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import unquote

import pg8000.native
from pgvector.pg8000 import register_vector

from gooddaynews.settings import get_settings


def ssl_context() -> ssl.SSLContext:
    """Encrypted connection. Supabase signs with its own CA: set DB_SSL_ROOT_CERT to the CA file
    (Project Settings > Database > SSL) to also verify the server; otherwise behave like sslmode=require."""
    cert = os.getenv("DB_SSL_ROOT_CERT")
    if cert:
        return ssl.create_default_context(cafile=cert)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


_URL_RE = re.compile(r"^postgres(?:ql)?://(?P<user>[^:@/]+):(?P<password>.*)@(?P<host>[^@:/]+)(?::(?P<port>\d+))?"
                     r"(?:/(?P<database>[^?]*))?(?:\?.*)?$")


@dataclass(frozen=True)
class DatabaseUrl:
    user: str
    password: str
    host: str
    port: int
    database: str


def parse_database_url(url: str) -> DatabaseUrl:
    """Split a postgresql:// URL. The password may contain @ [ ] # / and similar characters, which break the
    standard URL parser, so the host is taken after the LAST @. Percent-encoded values are decoded."""
    m = _URL_RE.match(url.strip())
    if not m:
        raise ValueError("DATABASE_URL should look like postgresql://user:password@host:5432/postgres")
    return DatabaseUrl(user=unquote(m["user"]), password=unquote(m["password"]), host=m["host"],
                       port=int(m["port"] or 5432), database=m["database"] or "postgres")


def connect() -> pg8000.native.Connection:
    url = get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
    parts = parse_database_url(url)
    conn = pg8000.native.Connection(
        user=parts.user,
        password=parts.password,
        host=parts.host,
        port=parts.port,
        database=parts.database,
        ssl_context=ssl_context(),
        timeout=30,
    )
    try:
        register_vector(conn)
    except Exception:
        # The vector type does not exist until schema.sql has created the extension.
        pass
    return conn


@contextmanager
def transaction():
    """Run statements in one transaction; commit on success, roll back on error."""
    conn = connect()
    try:
        conn.run("BEGIN")
        yield conn
        conn.run("COMMIT")
    except Exception:
        conn.run("ROLLBACK")
        raise
    finally:
        conn.close()
