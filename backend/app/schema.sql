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
CREATE TABLE IF NOT EXISTS api_plans (
 code text PRIMARY KEY, name text NOT NULL, description text NOT NULL DEFAULT '', sort_order int NOT NULL
);
CREATE TABLE IF NOT EXISTS api_capabilities (
 code text PRIMARY KEY, name text NOT NULL, layer text NOT NULL, active boolean NOT NULL DEFAULT true,
 default_requests_per_minute int NOT NULL CHECK(default_requests_per_minute>0),
 default_requests_per_day int NOT NULL CHECK(default_requests_per_day>0)
);
ALTER TABLE api_capabilities ADD COLUMN IF NOT EXISTS active boolean NOT NULL DEFAULT true;
CREATE TABLE IF NOT EXISTS api_plan_capabilities (
 plan_code text NOT NULL REFERENCES api_plans(code) ON DELETE CASCADE,
 capability text NOT NULL REFERENCES api_capabilities(code) ON DELETE CASCADE,
 requests_per_minute int NOT NULL CHECK(requests_per_minute>0),
 requests_per_day int NOT NULL CHECK(requests_per_day>0),
 PRIMARY KEY(plan_code,capability)
);
INSERT INTO api_plans(code,name,description,sort_order) VALUES
 ('basic','基础版','订阅内容与全文读取',1),
 ('research','研究版','内容、AI 洞察与质量证据',2),
 ('agent_pro','Agent 专业版','研究能力、搜索与自动化',3),
 ('enterprise','企业版','全部能力、团队与企业集成',4)
ON CONFLICT(code) DO NOTHING;
INSERT INTO api_capabilities(code,name,layer,default_requests_per_minute,default_requests_per_day) VALUES
 ('subscriptions.read','订阅列表','content',30,1000),
 ('feed.read','订阅 Feed','content',30,1000),
 ('article.read','文章全文','content',30,1000),
 ('docs.read','OpenAPI 文档','content',30,100),
 ('article.insight','文章洞察','insight',30,2000),
 ('account.insight','公众号画像','insight',30,2000),
 ('tags.read','标签目录','insight',30,2000),
 ('quality.evidence.read','质量评分证据','insight',30,2000),
 ('search.keyword','关键词搜索','search',60,10000),
 ('search.rerank','重排搜索','search',30,5000),
 ('search.semantic','语义搜索','search',30,2000),
 ('watchlist.manage','主题监控','automation',20,1000),
 ('webhook.receive','Webhook','enterprise',20,1000),
 ('team.manage','团队管理','enterprise',10,500),
 ('audit.read','审计记录','enterprise',10,500)
ON CONFLICT(code) DO NOTHING;
UPDATE api_capabilities SET active=false WHERE code IN
 ('search.semantic','watchlist.manage','webhook.receive','team.manage','audit.read');
INSERT INTO api_plan_capabilities(plan_code,capability,requests_per_minute,requests_per_day) VALUES
 ('basic','subscriptions.read',30,1000),('basic','feed.read',30,1000),('basic','article.read',30,1000),('basic','docs.read',30,100),
 ('research','subscriptions.read',60,10000),('research','feed.read',60,10000),('research','article.read',60,10000),('research','docs.read',60,1000),
 ('research','article.insight',30,2000),('research','account.insight',30,2000),('research','tags.read',30,2000),('research','quality.evidence.read',30,2000),
 ('agent_pro','subscriptions.read',120,50000),('agent_pro','feed.read',120,50000),('agent_pro','article.read',120,50000),('agent_pro','docs.read',120,5000),
 ('agent_pro','article.insight',60,10000),('agent_pro','account.insight',60,10000),('agent_pro','tags.read',60,10000),('agent_pro','quality.evidence.read',60,10000),
 ('agent_pro','search.keyword',60,10000),('agent_pro','search.rerank',30,5000),('agent_pro','search.semantic',30,2000),('agent_pro','watchlist.manage',20,1000),
 ('enterprise','subscriptions.read',300,200000),('enterprise','feed.read',300,200000),('enterprise','article.read',300,200000),('enterprise','docs.read',300,10000),
 ('enterprise','article.insight',120,50000),('enterprise','account.insight',120,50000),('enterprise','tags.read',120,50000),('enterprise','quality.evidence.read',120,50000),
 ('enterprise','search.keyword',120,50000),('enterprise','search.rerank',60,20000),('enterprise','search.semantic',60,10000),('enterprise','watchlist.manage',60,10000),
 ('enterprise','webhook.receive',60,10000),('enterprise','team.manage',30,2000),('enterprise','audit.read',30,2000)
ON CONFLICT(plan_code,capability) DO NOTHING;
CREATE TABLE IF NOT EXISTS user_api_access (
 user_id bigint PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 subscription_limit int NOT NULL DEFAULT 3 CHECK(subscription_limit>=0),
 plan_code text NOT NULL DEFAULT 'basic' REFERENCES api_plans(code),
 updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE user_api_access ADD COLUMN IF NOT EXISTS plan_code text NOT NULL DEFAULT 'basic' REFERENCES api_plans(code);
CREATE TABLE IF NOT EXISTS api_keys (
 id bigserial PRIMARY KEY, user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 name text NOT NULL, key_prefix text NOT NULL, token_hash text NOT NULL UNIQUE,
 scope_mode text NOT NULL DEFAULT 'inherit' CHECK(scope_mode IN ('inherit','restricted')),
 created_at timestamptz NOT NULL DEFAULT now(), last_used_at timestamptz, revoked_at timestamptz
);
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS scope_mode text NOT NULL DEFAULT 'inherit' CHECK(scope_mode IN ('inherit','restricted'));
CREATE TABLE IF NOT EXISTS api_key_capabilities (
 api_key_id bigint NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
 capability text NOT NULL REFERENCES api_capabilities(code) ON DELETE CASCADE,
 PRIMARY KEY(api_key_id,capability)
);
CREATE TABLE IF NOT EXISTS user_api_capabilities (
 user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 capability text NOT NULL REFERENCES api_capabilities(code) ON DELETE CASCADE,
 enabled boolean NOT NULL, requests_per_minute int CHECK(requests_per_minute IS NULL OR requests_per_minute>0),
 requests_per_day int CHECK(requests_per_day IS NULL OR requests_per_day>0), updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(user_id,capability)
);
CREATE TABLE IF NOT EXISTS api_usage_counters (
 user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 capability text NOT NULL REFERENCES api_capabilities(code) ON DELETE CASCADE,
 period text NOT NULL CHECK(period IN ('minute','day')), period_start timestamptz NOT NULL,
 calls int NOT NULL DEFAULT 0 CHECK(calls>=0), PRIMARY KEY(user_id,capability,period,period_start)
);
CREATE TABLE IF NOT EXISTS api_subscriptions (
 user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 account_id bigint NOT NULL REFERENCES official_accounts(id) ON DELETE CASCADE,
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(user_id,account_id)
);
CREATE INDEX IF NOT EXISTS api_keys_user_active ON api_keys(user_id) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS api_subscriptions_account ON api_subscriptions(account_id,user_id);
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

-- Independent source accounts and task leases (no permanent account assignment).
CREATE TABLE IF NOT EXISTS data_sources (
 id text PRIMARY KEY, name text NOT NULL, enabled boolean NOT NULL DEFAULT true
);
INSERT INTO data_sources VALUES ('weread','微信读书',true),('wechat-discovery','公众号发现',true) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS source_accounts (
 id bigserial PRIMARY KEY, source_id text NOT NULL REFERENCES data_sources(id) DEFAULT 'weread',
 name text NOT NULL, external_id text UNIQUE, credentials text NOT NULL DEFAULT '',
 enabled boolean NOT NULL DEFAULT true,
 health text NOT NULL DEFAULT 'unconfigured' CHECK(health IN ('unconfigured','healthy','expired','cooldown','error')),
 capability text NOT NULL DEFAULT 'unknown' CHECK(capability IN ('unknown','history','latest_only')),
 max_tasks int NOT NULL DEFAULT 1 CHECK(max_tasks BETWEEN 1 AND 4),
 max_subscriptions int NOT NULL DEFAULT 100 CHECK(max_subscriptions BETWEEN 1 AND 1000),
 consecutive_failures int NOT NULL DEFAULT 0, total_failures int NOT NULL DEFAULT 0,
 last_sync_at timestamptz, last_failure_at timestamptz, last_checked_at timestamptz,
 last_assigned_at timestamptz, cooldown_until timestamptz, next_request_at timestamptz,
 last_error text, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS source_subscriptions (
 account_id bigint NOT NULL REFERENCES official_accounts(id), source_id text NOT NULL REFERENCES data_sources(id) DEFAULT 'weread',
 external_id text NOT NULL, enabled boolean NOT NULL DEFAULT true,
 history_offset int NOT NULL DEFAULT 0, history_complete boolean NOT NULL DEFAULT false,
 capability text NOT NULL DEFAULT 'unknown', last_sync_at timestamptz, last_failure_at timestamptz,
 next_sync_at timestamptz NOT NULL DEFAULT now(), last_error text,
 PRIMARY KEY(account_id,source_id), UNIQUE(source_id,external_id)
);
CREATE TABLE IF NOT EXISTS source_memberships (
 source_account_id bigint REFERENCES source_accounts(id), account_id bigint REFERENCES official_accounts(id),
 joined_at timestamptz NOT NULL DEFAULT now(), last_used_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(source_account_id,account_id)
);
ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_kind_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_kind_check CHECK(kind IN ('discover','sync','parse','account_ai','article_ai','embedding'));
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS source_account_id bigint REFERENCES source_accounts(id);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS lease_token text;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS heartbeat_at timestamptz;
CREATE TABLE IF NOT EXISTS crawl_attempts (
 id bigserial PRIMARY KEY, job_id bigint NOT NULL REFERENCES jobs(id),
 source_account_id bigint NOT NULL REFERENCES source_accounts(id),
 lease_token text NOT NULL UNIQUE, status text NOT NULL DEFAULT 'running',
 started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz, error_code text, error text
);
CREATE TABLE IF NOT EXISTS article_origins (
 source_id text NOT NULL REFERENCES data_sources(id), external_id text NOT NULL,
 article_id bigint NOT NULL REFERENCES articles(id), book_id text NOT NULL,
 fetched_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(source_id,external_id)
);
CREATE TABLE IF NOT EXISTS article_embeddings (
 article_id bigint PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
 model text NOT NULL, content_hash text NOT NULL, embedding double precision[] NOT NULL,
 generated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS discovery_requests (
 query text PRIMARY KEY, job_id bigint REFERENCES jobs(id), requested_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS jobs_source_lease ON jobs(source_account_id) WHERE status='running';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS execution_token text;
ALTER TABLE source_accounts ADD COLUMN IF NOT EXISTS maintenance_until timestamptz;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS body_publish_time timestamptz;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS body_error text;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS body_failures integer NOT NULL DEFAULT 0;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS body_retry_after timestamptz;
