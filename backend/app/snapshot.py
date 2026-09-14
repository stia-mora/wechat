"""Portable catalog export/import; excludes users, credentials, and private activity."""

import argparse
import json
from pathlib import Path

from psycopg import sql
from psycopg.types.json import Jsonb

from .db import db, initialize
from .repository import index_account, index_article

TABLES = [
    "categories",
    "official_accounts",
    "official_account_categories",
    "tags",
    "official_account_tags",
    "articles",
    "article_tags",
    "ai_account_profiles",
    "ai_article_summaries",
]


def export_catalog(path):
    with db() as conn:
        data = {
            table: conn.execute(
                sql.SQL("SELECT * FROM {}").format(sql.Identifier(table))
            ).fetchall()
            for table in TABLES
        }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"Exported {len(data['official_accounts'])} accounts, {len(data['articles'])} articles")


def import_catalog(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    initialize()
    with db() as conn:
        if conn.execute("SELECT 1 FROM official_accounts LIMIT 1").fetchone():
            raise ValueError("只允许导入空账号库，避免覆盖现有数据")
        for table in TABLES:
            for row in data.get(table, []):
                columns = list(row)
                values = [
                    Jsonb(row[k]) if isinstance(row[k], (dict, list)) else row[k] for k in columns
                ]
                conn.execute(
                    sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING").format(
                        sql.Identifier(table),
                        sql.SQL(",").join(map(sql.Identifier, columns)),
                        sql.SQL(",").join(sql.Placeholder() for _ in columns),
                    ),
                    values,
                )
            if data.get(table) and "id" in data[table][0]:
                conn.execute(
                    sql.SQL(
                        "SELECT setval(pg_get_serial_sequence(%s,'id'), greatest(1,(SELECT max(id) FROM {})))"
                    ).format(sql.Identifier(table)),
                    (table,),
                )
        for account in conn.execute("SELECT id FROM official_accounts").fetchall():
            index_account(conn, account["id"])
        for article in conn.execute("SELECT id FROM articles").fetchall():
            index_article(conn, article["id"])
    print("Catalog imported and search index rebuilt")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["export", "import"])
    parser.add_argument("path")
    args = parser.parse_args()
    (export_catalog if args.action == "export" else import_catalog)(args.path)
