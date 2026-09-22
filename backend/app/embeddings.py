import hashlib
import math
import os

import httpx

from .db import db


def request_embedding(text, timeout):
    key = os.getenv("EMBEDDING_API_KEY")
    model = os.getenv("EMBEDDING_MODEL")
    if not key or not model:
        return None
    with httpx.Client(timeout=timeout, trust_env=False) as client:
        response = client.post(
            os.getenv("EMBEDDING_BASE_URL", "https://api.openai.com/v1").rstrip("/")
            + "/embeddings",
            headers={"Authorization": "Bearer " + key},
            json={
                "model": model,
                "input": text,
                **({"truncate": "right"} if "VL-Embedding" in model else {}),
            },
        )
        response.raise_for_status()
    vector = response.json()["data"][0]["embedding"]
    if (
        not vector
        or len(vector) > 16384
        or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in vector)
    ):
        raise ValueError("Embedding 返回无效向量")
    # Providers may serialize zero as an integer; psycopg arrays require one numeric type.
    vector = [float(v) for v in vector]
    return model, vector


def embed_query(query):
    return request_embedding(query[:200], timeout=12)


def refresh_account_embedding(conn, account_id, model):
    row = conn.execute(
        """WITH source AS (
          SELECT e.embedding FROM article_embeddings e JOIN articles ar ON ar.id=e.article_id
          WHERE ar.account_id=%s AND ar.status='ready' AND e.model=%s
        ), dimensions AS (
          SELECT component.ordinality,avg(component.value)::double precision AS value
          FROM source CROSS JOIN unnest(source.embedding) WITH ORDINALITY AS component(value,ordinality)
          GROUP BY component.ordinality
        )
        SELECT (SELECT count(*) FROM source) AS source_embedding_count,
          array_agg(value ORDER BY ordinality) AS embedding FROM dimensions""",
        (account_id, model),
    ).fetchone()
    if not row or not row["embedding"]:
        conn.execute("DELETE FROM account_embeddings WHERE account_id=%s", (account_id,))
        return 0
    conn.execute(
        """INSERT INTO account_embeddings(account_id,model,source_embedding_count,embedding)
        VALUES (%s,%s,%s,%s) ON CONFLICT(account_id) DO UPDATE SET model=EXCLUDED.model,
        source_embedding_count=EXCLUDED.source_embedding_count,embedding=EXCLUDED.embedding,generated_at=now()""",
        (account_id, model, row["source_embedding_count"], row["embedding"]),
    )
    return row["source_embedding_count"]


def refresh_account(payload):
    with db() as conn:
        row = conn.execute(
            "SELECT model FROM article_embeddings e JOIN articles ar ON ar.id=e.article_id WHERE ar.account_id=%s ORDER BY e.generated_at DESC LIMIT 1",
            (payload["target_id"],),
        ).fetchone()
        count = refresh_account_embedding(conn, payload["target_id"], row["model"]) if row else 0
    return {"account_id": payload["target_id"], "source_embedding_count": count}


def generate(payload):
    key = os.getenv("EMBEDDING_API_KEY")
    model = os.getenv("EMBEDDING_MODEL")
    if not key or not model:
        return {"skipped": True, "reason": "未配置 Embedding 模型"}
    with db() as conn:
        row = conn.execute(
            "SELECT account_id,content_text FROM articles WHERE id=%s", (payload["target_id"],)
        ).fetchone()
        previous = conn.execute(
            "SELECT model,content_hash FROM article_embeddings WHERE article_id=%s",
            (payload["target_id"],),
        ).fetchone()
    if not row or not row["content_text"]:
        raise ValueError("文章缺少正文")
    text = row["content_text"][:24000]
    digest = hashlib.sha256(text.encode()).hexdigest()
    if previous and previous["model"] == model and previous["content_hash"] == digest:
        with db() as conn:
            refresh_account_embedding(conn, row["account_id"], model)
        return {"cached": True}
    _, vector = request_embedding(text, timeout=120)
    with db() as conn:
        conn.execute(
            """INSERT INTO article_embeddings(article_id,model,content_hash,embedding) VALUES (%s,%s,%s,%s)
            ON CONFLICT(article_id) DO UPDATE SET model=EXCLUDED.model,content_hash=EXCLUDED.content_hash,embedding=EXCLUDED.embedding,generated_at=now()""",
            (payload["target_id"], model, digest, vector),
        )
        refresh_account_embedding(conn, row["account_id"], model)
    return {"article_id": payload["target_id"], "dimensions": len(vector), "model": model}
