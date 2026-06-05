# Riffado deployment (local-only, hardened)

Self-hosted Riffado as the Plaud sync + storage layer for `plaudautomation`.
Pinned to **0.5.6**, bound to **127.0.0.1**, reviewed against the project's security gate.

> **Version note:** initially pinned 0.5.4, but it has a rate-limiter bug
> (`ERR_INVALID_ARG_TYPE`, a `Date` passed where a string is expected) that
> crashes **every** `/api/v1/*` and `/api/plaud/sync` request — fixed in 0.5.5.
> We run **0.5.6** (latest patch on the 0.5 line). The security review below was
> re-verified against the 0.5.6 image (same hardened profile; digest
> `sha256:32377932b9729fbf2fd164892aaf384bc490aecff0aee91ff5c26c36cb3cfd28`).

## Security review (SEC-03 / SEC-05) — what we found and did

Reviewed upstream `docker-compose.yml` and `.env.example` at tag `v0.5.4`:

| Item | Upstream default | Risk | Our setting |
|---|---|---|---|
| Image tag | `:latest` | unpinned (SEC-01) | `RIFFADO_VERSION=0.5.4` |
| App/DB ports | `0.0.0.0:3000`, `0.0.0.0:5432` | exposed to LAN | `127.0.0.1:3000`; DB not published |
| Update check | `api.github.com` ping | runtime egress to GitHub | `DISABLE_UPDATE_CHECK=true` |
| Rybbit analytics | unset | telemetry | unset (hosted-only, inert) |
| `ADMIN_EMAILS` (maintainer) | commented | maintainer admin | unset (hosted-only, inert) |
| Webshare proxy / `PLAUD_PROXY_SCOPE` | unset | 3rd-party proxy for Plaud traffic | unset → direct to Plaud |
| Storage | `local` | — | `local`, no S3 |
| SMTP / public webhooks | unset / off | email/exfil | off; webhook targets localhost-only |

**Resulting runtime egress:** `api*.plaud.ai` + `resource.plaud.ai` only.

## First run (no Plaud credentials yet — SEC-02)

```sh
cd deploy/riffado
cp .env.example .env
# fill secrets:
#   openssl rand -hex 32  -> BETTER_AUTH_SECRET
#   openssl rand -hex 32  -> ENCRYPTION_KEY
#   openssl rand -hex 24  -> POSTGRES_PASSWORD

docker compose config                 # render & sanity-check (SEC-03)
docker compose pull                   # pull pinned image (SEC-02: before creds)
docker compose up -d
docker compose ps                     # confirm 127.0.0.1 bindings
docker port riffado-app               # must show 127.0.0.1:3000 only
```

Then open http://127.0.0.1:3000, create the single admin user, and **only after the
egress checks pass** connect the Plaud account and sync one non-sensitive recording.

## Lock-down after first user

Set `DISABLE_REGISTRATION=true` in `.env`, then `docker compose up -d` to recreate.

## Egress evidence

Runtime network validation via a `tcpdump` sidecar sharing the app container's
network namespace, capturing a live sync:

```sh
mkdir -p audit
docker run -d --name riffado-capture --net container:riffado-app \
  -v "$PWD/audit:/cap" nicolaka/netshoot tcpdump -i any -n -w /cap/sync.pcap
# ...click "Sync Device" in the UI, let it finish...
docker rm -f riffado-capture

# external destinations (TCP SYNs, excluding local/private):
docker run --rm -v "$PWD/audit:/cap" nicolaka/netshoot \
  tcpdump -r /cap/sync.pcap -n 'tcp[tcpflags] & tcp-syn != 0 and tcp[tcpflags] & tcp-ack == 0'
# hostnames on the wire (TLS SNI is plaintext):
strings audit/sync.pcap | grep -iE 'plaud|notion|github|sentry|posthog|rybbit|amazonaws'
```

**Result (verified):** the only external host contacted during a sync was
`api-apse1.plaud.ai` (→ 104.18.6/7.192, confirmed = `api.plaud.ai`). Everything
else was local (localhost `POST /api/plaud/sync` + internal Postgres). No GitHub,
Notion, analytics, telemetry, Sentry/PostHog/Rybbit, or S3. Matches the approved
"Runtime: Plaud endpoint only" boundary. The `audit/` pcap is gitignored.
