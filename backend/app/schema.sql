CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE TABLE IF NOT EXISTS categories (
 id bigserial PRIMARY KEY, name text NOT NULL, slug text UNIQUE NOT NULL,
 parent_id bigint REFERENCES categories(id), sort_order int NOT NULL DEFAULT 0,
 status text NOT NULL DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS official_accounts (
 id bigserial PRIMARY KEY, platform text NOT NULL DEFAULT 'wechat',
 source_id text NOT NULL, name text NOT NULL, wechat_id text NOT NULL DEFAULT '',
 avatar_url text NOT NULL DEFAULT '', description text NOT NULL DEFAULT '',
 original_description text NOT NULL DEFAULT '', verified_type text NOT NULL DEFAULT '',
 source_url text NOT NULL DEFAULT '', source_provider text NOT NULL DEFAULT 'wechat-download-api',
 primary_category_id bigint REFERENCES categories(id), account_type text NOT NULL DEFAULT '',
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','hidden','error')),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 last_crawled_at timestamptz, last_article_at timestamptz,
 UNIQUE(platform,source_id)
);
CREATE TABLE IF NOT EXISTS official_account_categories (
 account_id bigint REFERENCES official_accounts(id) ON DELETE CASCADE,
 category_id bigint REFERENCES categories(id), PRIMARY KEY(account_id,category_id)
);
CREATE TABLE IF NOT EXISTS tags (id bigserial PRIMARY KEY, name text UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS official_account_tags (
 account_id bigint REFERENCES official_accounts(id) ON DELETE CASCADE,
 tag_id bigint REFERENCES tags(id) ON DELETE CASCADE, PRIMARY KEY(account_id,tag_id)
);
CREATE TABLE IF NOT EXISTS articles (
 id bigserial PRIMARY KEY, account_id bigint NOT NULL REFERENCES official_accounts(id),
 source_key text UNIQUE NOT NULL, title text NOT NULL, author text NOT NULL DEFAULT '',
 source_url text NOT NULL, cover_url text NOT NULL DEFAULT '', content_html text NOT NULL DEFAULT '',
 content_text text NOT NULL DEFAULT '', summary text NOT NULL DEFAULT '', word_count int NOT NULL DEFAULT 0,
 publish_time timestamptz, crawl_time timestamptz NOT NULL DEFAULT now(),
 status text NOT NULL DEFAULT 'metadata' CHECK(status IN ('metadata','ready','hidden','error')),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS article_tags (
 article_id bigint REFERENCES articles(id) ON DELETE CASCADE, tag_id bigint REFERENCES tags(id) ON DELETE CASCADE,
 PRIMARY KEY(article_id,tag_id)
);
CREATE TABLE IF NOT EXISTS ai_account_profiles (
 account_id bigint PRIMARY KEY REFERENCES official_accounts(id) ON DELETE CASCADE,
 data jsonb NOT NULL, model_name text NOT NULL, prompt_version text NOT NULL,
 source_article_count int NOT NULL, generated_at timestamptz NOT NULL DEFAULT now(),
 reviewed boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS ai_article_summaries (
 article_id bigint PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
 data jsonb NOT NULL, model_name text NOT NULL, prompt_version text NOT NULL,
 generated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE ai_account_profiles ADD COLUMN IF NOT EXISTS source_total_count int NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS users (
 id bigserial PRIMARY KEY, email text UNIQUE NOT NULL, display_name text NOT NULL,
 password_hash text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash text PRIMARY KEY, user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 expires_at timestamptz NOT NULL DEFAULT now() + interval '30 days'
);
CREATE TABLE IF NOT EXISTS user_following (
 user_id bigint REFERENCES users(id) ON DELETE CASCADE, account_id bigint REFERENCES official_accounts(id) ON DELETE CASCADE,
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(user_id,account_id)
);
CREATE TABLE IF NOT EXISTS collections (
 id bigserial PRIMARY KEY, user_id bigint REFERENCES users(id) ON DELETE CASCADE,
 account_id bigint REFERENCES official_accounts(id) ON DELETE CASCADE,
 article_id bigint REFERENCES articles(id) ON DELETE CASCADE,
 created_at timestamptz NOT NULL DEFAULT now(), CHECK(num_nonnulls(account_id,article_id)=1),
 UNIQUE(user_id,account_id), UNIQUE(user_id,article_id)
);
CREATE TABLE IF NOT EXISTS browsing_history (
 user_id bigint REFERENCES users(id) ON DELETE CASCADE, kind text NOT NULL CHECK(kind IN ('account','article')),
 target_id bigint NOT NULL, visited_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(user_id,kind,target_id)
);
CREATE TABLE IF NOT EXISTS jobs (
 id bigserial PRIMARY KEY, kind text NOT NULL CHECK(kind IN ('discover','sync','parse','account_ai','article_ai')),
 payload jsonb NOT NULL DEFAULT '{}', dedupe_key text NOT NULL,
 status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','done','failed','blocked')),
 attempts int NOT NULL DEFAULT 0, max_attempts int NOT NULL DEFAULT 3, result jsonb,
 error text, created_at timestamptz NOT NULL DEFAULT now(), started_at timestamptz,
 finished_at timestamptz, run_after timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS jobs_active_key ON jobs(dedupe_key) WHERE status IN ('queued','running');
CREATE TABLE IF NOT EXISTS settings (key text PRIMARY KEY, value jsonb NOT NULL);
INSERT INTO settings VALUES ('ranking','{"quality":0.35,"activity":0.3,"completeness":0.2,"following":0.15}') ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS search_documents (
 kind text NOT NULL, target_id bigint NOT NULL, body text NOT NULL, document tsvector,
 PRIMARY KEY(kind,target_id)
);
CREATE INDEX IF NOT EXISTS search_body_trgm ON search_documents USING gin(body gin_trgm_ops);
CREATE INDEX IF NOT EXISTS search_fts ON search_documents USING gin(document);
CREATE INDEX IF NOT EXISTS accounts_name_trgm ON official_accounts USING gin(name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS articles_account_time ON articles(account_id,publish_time DESC);
CREATE INDEX IF NOT EXISTS jobs_poll ON jobs(status,run_after);
CREATE OR REPLACE VIEW account_stats AS
 SELECT a.id AS account_id, count(ar.id)::int AS article_count,
 count(ar.id) FILTER(WHERE ar.publish_time>now()-interval '7 days')::int AS articles_last_7d,
 count(ar.id) FILTER(WHERE ar.publish_time>now()-interval '30 days')::int AS articles_last_30d,
 count(ar.id) FILTER(WHERE ar.publish_time>now()-interval '90 days')::int AS articles_last_90d,
 count(ar.id) FILTER(WHERE ar.status='ready')::int AS readable_count,
 least(100,count(ar.id) FILTER(WHERE ar.publish_time>now()-interval '30 days')*3.0) AS active_score
 FROM official_accounts a LEFT JOIN articles ar ON ar.account_id=a.id AND ar.status<>'hidden' GROUP BY a.id;
CREATE OR REPLACE VIEW article_stats AS
 SELECT a.id AS article_id, (SELECT count(*) FROM collections c WHERE c.article_id=a.id)::int AS collection_count
 FROM articles a;
