import os
from contextlib import contextmanager
from pathlib import Path
from threading import BoundedSemaphore

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
connection_slots = BoundedSemaphore(max(1, int(os.getenv("DB_MAX_CONNECTIONS", "6"))))


class DatabaseBusy(Exception):
    """No connection slot is available; callers may retry, without a raw DSN."""


@contextmanager
def db():
    if not connection_slots.acquire(timeout=float(os.getenv("DB_ACQUIRE_TIMEOUT_SECONDS", "2"))):
        raise DatabaseBusy()
    try:
        statement_ms = max(1, int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "30000")))
        with psycopg.connect(
            os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=5,
            options=f"-c statement_timeout={statement_ms} -c lock_timeout=5000 -c idle_in_transaction_session_timeout=60000",
        ) as conn:
            yield conn
    finally:
        connection_slots.release()


def initialize():
    with db() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(271828)")
        from .credentials import cipher

        cipher()
        conn.execute(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
        from .taxonomy import CATEGORIES

        for order, (name, children) in enumerate(CATEGORIES.items()):
            parent = conn.execute(
                "INSERT INTO categories(name,slug,sort_order) VALUES (%s,%s,%s) ON CONFLICT(slug) DO UPDATE SET slug=EXCLUDED.slug RETURNING id",
                (name, name, order),
            ).fetchone()["id"]
            for index, child in enumerate(children):
                conn.execute(
                    "INSERT INTO categories(name,slug,parent_id,sort_order) VALUES (%s,%s,%s,%s) ON CONFLICT(slug) DO NOTHING",
                    (child, name + "/" + child, parent, index),
                )
