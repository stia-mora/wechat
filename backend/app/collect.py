"""Collect real, exact-name matches from the reference API; never seed account records."""

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from psycopg.types.json import Jsonb

from .crawler import SourceBlocked, SourceClient
from .db import db, initialize
from .repository import enqueue, index_account, set_tags

# Human-curated discovery queries, not imported records. Only API-returned exact names
# are approved; similarly named results remain pending for manual review.
QUERIES = {
    "科技": [
        "机器之心",
        "量子位",
        "新智元",
        "极客公园",
        "InfoQ",
        "雷峰网",
        "爱范儿",
        "36氪",
        "虎嗅APP",
        "钛媒体",
        "差评",
        "果壳",
        "科学大院",
        "DeepTech深科技",
        "科技日报",
    ],
    "财经": [
        "第一财经",
        "财新",
        "经济观察报",
        "证券时报",
        "中国证券报",
        "上海证券报",
        "每日经济新闻",
        "华尔街见闻",
        "财联社",
        "中国基金报",
        "券商中国",
        "21世纪经济报道",
        "经济日报",
        "商业评论",
        "正和岛",
    ],
    "教育": [
        "清华大学",
        "北京大学",
        "浙江大学",
        "复旦大学",
        "上海交通大学",
        "南京大学",
        "武汉大学",
        "中山大学",
        "中国科学技术大学",
        "南开大学",
        "中国人民大学",
        "北京师范大学",
        "中国教育报",
        "中国教育在线",
        "新东方",
    ],
    "生活": [
        "三联生活周刊",
        "一条",
        "读者",
        "十点读书",
        "看理想",
        "单读",
        "新世相",
        "人物",
        "丁香医生",
        "健康时报",
        "下厨房",
        "穷游网",
        "孤独星球",
        "国家地理中文网",
        "博物",
    ],
}


def export_report(path):
    with db() as conn:
        accounts = conn.execute(
            "SELECT a.id,a.name,a.source_id,a.wechat_id,a.source_url,a.source_provider,a.status,c.name AS category,a.last_crawled_at,s.article_count,s.readable_count FROM official_accounts a LEFT JOIN categories c ON c.id=a.primary_category_id JOIN account_stats s ON s.account_id=a.id ORDER BY a.id"
        ).fetchall()
        jobs = conn.execute(
            "SELECT id,kind,status,error,result,created_at,finished_at FROM jobs ORDER BY id"
        ).fetchall()
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "local wechat-download-api, actual WeChat searchbiz responses",
        "unique_accounts": len({a["source_id"] for a in accounts}),
        "approved_accounts": sum(a["status"] == "approved" for a in accounts),
        "accounts": accounts,
        "jobs": jobs,
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return report


def collect(target, wait_login, report_path):
    initialize()
    while True:
        try:
            response = httpx.get(
                os.environ["SOURCE_API_URL"] + "/api/admin/status", timeout=5, trust_env=False
            )
            response.raise_for_status()
            status = response.json()
            if status.get("loggedIn") and not status.get("isExpired"):
                break
        except (httpx.HTTPError, ValueError):
            pass
        if not wait_login:
            raise SourceBlocked("请先在本机参考服务扫码登录")
        print("Waiting for source login...", flush=True)
        time.sleep(20)
    source = SourceClient()
    with db() as conn:
        categories = {
            r["name"]: r["id"]
            for r in conn.execute(
                "SELECT id,name FROM categories WHERE parent_id IS NULL"
            ).fetchall()
        }
    for category, names in QUERIES.items():
        for name in names:
            with db() as conn:
                n = conn.execute(
                    "SELECT count(*) AS n FROM official_accounts WHERE status='approved'"
                ).fetchone()["n"]
                if n >= target:
                    report = export_report(report_path)
                    print(
                        f"Complete: {report['unique_accounts']} unique / {report['approved_accounts']} reviewed",
                        flush=True,
                    )
                    return
                if conn.execute(
                    "SELECT id FROM official_accounts WHERE name=%s AND status='approved'", (name,)
                ).fetchone():
                    continue
                payload = {"query": name, "category_id": categories[category]}
                job_id = enqueue(conn, "discover", payload)
                if not job_id:
                    continue
                conn.execute(
                    "UPDATE jobs SET status='running',attempts=1,started_at=now() WHERE id=%s",
                    (job_id,),
                )
            try:
                result = source.discover(payload)
                with db() as conn:
                    for account in result["accounts"]:
                        if account["name"].casefold() != name.casefold():
                            continue
                        conn.execute(
                            "UPDATE official_accounts SET status='approved',primary_category_id=%s WHERE id=%s",
                            (categories[category], account["id"]),
                        )
                        set_tags(conn, account["id"], [category])
                        index_account(conn, account["id"])
                    conn.execute(
                        "UPDATE jobs SET status='done',result=%s,finished_at=now() WHERE id=%s",
                        (Jsonb(result), job_id),
                    )
                print(f"{category} / {name}: {len(result['accounts'])} returned", flush=True)
                export_report(report_path)
            except Exception as exc:
                with db() as conn:
                    conn.execute(
                        "UPDATE jobs SET status=%s,error=%s,finished_at=now() WHERE id=%s",
                        (
                            "blocked" if isinstance(exc, SourceBlocked) else "failed",
                            str(exc)[:1000],
                            job_id,
                        ),
                    )
                export_report(report_path)
                if isinstance(exc, SourceBlocked):
                    raise
                print(f"{name}: {exc}", flush=True)
    report = export_report(report_path)
    if report["approved_accounts"] < target:
        raise RuntimeError(
            f"Only {report['approved_accounts']} exact matches; review pending results or extend discovery queries"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=50)
    parser.add_argument("--wait-login", action="store_true")
    parser.add_argument("--export-only", action="store_true")
    parser.add_argument("--report", default="../data/collection-report.json")
    args = parser.parse_args()
    if args.export_only:
        export_report(args.report)
    else:
        collect(args.target, args.wait_login, args.report)
