"""Link profile topics to the existing taxonomy, without inventing categories."""

ALIASES = {
    "人工智能": ["ai", "人工智能"],
    "大模型": ["大模型", "llm"],
    "AI-Agent": ["agent", "智能体"],
    "AI编程": ["ai编程", "编程助手"],
    "股票": ["股票", "股市", "a股"],
    "证券": ["证券", "资本市场"],
    "大学": ["大学", "高校"],
    "K12": ["k12", "基础教育", "中小学"],
    "旅行": ["旅行", "旅游"],
    "汽车科技": ["智能驾驶", "汽车科技", "自动驾驶"],
}


def link_profile_categories(conn, account_id, profile):
    topics = [
        t["name"].casefold()
        for t in profile.get("topic_distribution", [])
        if t.get("percentage", 0) >= 5
    ]
    categories = conn.execute(
        """SELECT c.id,c.name FROM categories c JOIN official_accounts a
        ON a.primary_category_id=c.parent_id WHERE a.id=%s AND c.status='active' """,
        (account_id,),
    ).fetchall()
    for category in categories:
        terms = ALIASES.get(category["name"], [category["name"].casefold()])
        if any(term in topic for term in terms for topic in topics):
            conn.execute(
                "INSERT INTO official_account_categories(account_id,category_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                (account_id, category["id"]),
            )
