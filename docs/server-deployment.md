# ECS deployment

The server deployment uses the committed application code plus a private migration
archive. The archive contains PostgreSQL, environment settings, credential keys,
private exports, and the bridge service's local state. Do not add any of these
files to Git.

Create the archive on the local machine before transferring it. The script refuses
to overwrite an existing archive and removes only its own temporary staging
directory.

```powershell
.\scripts\create-server-migration.ps1 -OutputPath "$env:TEMP\wechat-migration.tgz"
```

From the repository root on the server, after copying the archive to
`/root/wechat-migration.tgz`:

```sh
mkdir -p data/private data/source-bridge/upstream-data
tar -xzf /root/wechat-migration.tgz
docker compose -f compose.yaml -f compose.server.yaml up -d db
docker compose -f compose.yaml -f compose.server.yaml exec -T db \
  pg_restore -U wechat -d wechat_source --clean --if-exists < migration/postgres.dump
docker compose -f compose.yaml -f compose.server.yaml up -d --build
docker compose -f compose.yaml -f compose.server.yaml ps
curl -fsS http://127.0.0.1:8500/api/health
```

The server compose file exposes only the Next.js application on TCP port 80 at
`http://SERVER/wechat`.
PostgreSQL and the API remain bound to loopback, and the source bridge remains
on the internal Docker network. The ECS security group must permit inbound TCP
80 before the site can be reached from the Internet. Add this rule under the
security group's **inbound** direction, not its outbound direction.

For an update, pull the target commit and recreate the application containers:

```sh
git pull --ff-only
docker compose -f compose.yaml -f compose.server.yaml up -d --build
```

## Restricted server egress

If the ECS cannot reach GitHub, Docker Hub, or package registries reliably, build
the images on a machine with normal Internet access and transfer them over SSH.
Use the server's Compose project name so the loaded tags match the service tags:

```powershell
docker compose -p wechat -f compose.yaml -f compose.server.yaml build
docker image save -o "$env:TEMP\wechat-images.tar" `
  wechat-api wechat-worker wechat-web wechat-source
scp "$env:TEMP\wechat-images.tar" root@SERVER:/root/wechat-images.tar
```

Then, on the server:

```sh
docker load -i /root/wechat-images.tar
cd /opt/wechat
docker compose -f compose.yaml -f compose.server.yaml up -d --no-build
```

For a code-only update when `git pull` also times out, transfer an incremental Git
bundle from the local machine and fast-forward it on the server. Confirm the
current server commit first, then use it as the bundle base; this leaves ignored
private data and runtime-generated reports untouched.

## Directory-only expansion

The article worker now requires the `articles` profile. To pause article collection
and discover at least 10,000 real, unique WeChat accounts:

```sh
docker compose -f compose.yaml -f compose.server.yaml --profile articles stop worker
docker compose -f compose.yaml -f compose.server.yaml --profile directory up -d --build directory-discovery
```

The collector searches the authenticated WeChat API, pages results, and deduplicates
by `(platform, source_id)`. Search terms are never imported as account records.
New accounts remain pending review with `article_collection_enabled=false`;
existing accounts retain their collection setting. No article tasks are created.
Progress is saved in `data/private/directory-discovery.json` after every page.
The process waits on expired login or rate limits and resumes the same page after
login is restored. Exhausting the queries does not report the target as achieved.
The target includes the existing real accounts; it is not a promise of 10,000 new ones.

To resume existing article collection explicitly, enable the `articles` profile
and start `worker`. Newly discovered directory accounts remain excluded until
their `article_collection_enabled` field is explicitly enabled.
