"""Postgres connection (Supabase) using the pure-Python pg8000 driver."""

import os
import ssl
from contextlib import contextmanager
from urllib.parse import unquote, urlparse

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


def connect() -> pg8000.native.Connection:
    url = get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
    parts = urlparse(url)
    conn = pg8000.native.Connection(
        user=unquote(parts.username or ""),
        password=unquote(parts.password or ""),
        host=parts.hostname,
        port=parts.port or 5432,
        database=(parts.path or "/postgres").lstrip("/"),
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
