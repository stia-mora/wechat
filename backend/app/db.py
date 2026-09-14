import os
from contextlib import contextmanager
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


@contextmanager
def db():
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        yield conn


def initialize():
    with db() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(271828)")
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
