import hashlib
import math
import os

import httpx

from .crawler import SourceBlocked
from .db import db


def generate(payload):
    key = os.getenv("EMBEDDING_API_KEY")
    model = os.getenv("EMBEDDING_MODEL")
    if not key or not model:
        raise SourceBlocked("未配置 EMBEDDING_API_KEY / EMBEDDING_MODEL，向量任务等待配置")
    with db() as conn:
        row = conn.execute(
            "SELECT content_text FROM articles WHERE id=%s", (payload["target_id"],)
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
        return {"cached": True}
    with httpx.Client(timeout=120, trust_env=False) as client:
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
    with db() as conn:
        conn.execute(
            """INSERT INTO article_embeddings(article_id,model,content_hash,embedding) VALUES (%s,%s,%s,%s)
            ON CONFLICT(article_id) DO UPDATE SET model=EXCLUDED.model,content_hash=EXCLUDED.content_hash,embedding=EXCLUDED.embedding,generated_at=now()""",
            (payload["target_id"], model, digest, vector),
        )
    return {"article_id": payload["target_id"], "dimensions": len(vector), "model": model}
