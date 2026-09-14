"""Rerank a bounded set of PostgreSQL search candidates."""

import math
import os

import httpx


def rerank(query, rows):
    key, model = os.getenv("RERANK_API_KEY"), os.getenv("RERANK_MODEL")
    if not rows or not key or not model:
        return rows, "database"
    with httpx.Client(timeout=30, trust_env=False) as client:
        response = client.post(
            os.environ["RERANK_BASE_URL"].rstrip("/") + "/rerank",
            headers={"Authorization": "Bearer " + key},
            json={
                "model": model,
                "query": query,
                "documents": [
                    (r["title"] + "\n" + r.get("summary", "") + "\n" + r.get("content_text", ""))[
                        :6000
                    ]
                    for r in rows
                ],
                "top_n": len(rows),
                "return_documents": False,
            },
        )
        response.raise_for_status()
    results = response.json()["results"]
    indices = [r["index"] for r in results]
    if sorted(indices) != list(range(len(rows))) or any(
        not math.isfinite(r["relevance_score"]) for r in results
    ):
        raise ValueError("重排返回无效结果")
    results.sort(key=lambda r: r["relevance_score"], reverse=True)
    return [{**rows[r["index"]], "relevance_score": r["relevance_score"]} for r in results], model
