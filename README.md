# DevOps / Platform Engineer — Case Study (starter)

This repo gives you a running start so you can spend your ~3 hours on the **platform work**, not scaffolding.

## What's provided
- `app/` — a trivial Python (FastAPI) orders API. **This is not what we're assessing** — extend or replace it freely.
- `schema.sql` — the baseline `orders` table, pre-seeded. **Your migration evolves this.**
- `docker-compose.yml` — Postgres, pre-wired and seeded. You add the `app` service once you've written the Dockerfile.
- `Dockerfile` — a bare stub to harden.
- `migrations/` — where your migration goes (**the centrepiece** — read that README).
- `.github/workflows/ci.yml` — a skeleton pipeline to fill in.

## What you build
The containerisation, the CI/CD pipeline, **the safe schema migration (priority)**, and the observability — see the brief below.

## How to run
```bash
docker compose up        # brings up Postgres (and your app, once added)
```
The API needs `DB_URL` (default `postgresql://app:app@localhost:5432/app`).

## Database migration — safety reasoning

The baseline `orders` table gets one change: a `currency` column, rolled out as
**expand → backfill → contract** (`migrations/sql/0001_*`, `migrations/backfill_currency.py`,
`migrations/sql/0002_*`). CI (`.github/workflows/ci.yml`) and local dev (`docker-compose.yml`'s
`migrate` service) both run the same three steps against their own Postgres.

**Expand (`0001`) is backwards-compatible.** `currency` is added as a *nullable* column —
no default, no constraint. The old app code (which never mentions `currency`) keeps working
unmodified; the new app code (`app/main.py`, `Order.currency: str = "ZAR"`) also works, since
old-shaped requests without a `currency` field simply default to `"ZAR"`. Both versions of the
app can run side by side during the rollout — there's no cutover moment.

**The backfill is safe under live traffic because it's batched and idempotent.**
`backfill_currency.py` updates existing rows `LIMIT 500` (`FOR UPDATE SKIP LOCKED`) at a time,
each batch its own transaction, so it never holds a long lock on the table. It always targets
`WHERE currency IS NULL`, so progress lives entirely in the data — running it again after a
crash just continues from wherever it stopped. There is no separate progress-tracking state to
get out of sync.

**Contract (`0002`) only happens once the backfill has actually finished**, and even then
without a blocking table rewrite: it adds `CHECK (currency IS NOT NULL) NOT VALID` (instant —
only blocks *new* violations) and then runs `VALIDATE CONSTRAINT`, which scans existing rows
under a `SHARE UPDATE EXCLUSIVE` lock rather than the much heavier lock a plain
`ALTER COLUMN ... SET NOT NULL` would need. If you run `0002` before the backfill is done, it
fails loudly (a row violates the check) instead of silently corrupting the rollout — that's the
correct failure mode.

**Mid-run failure: detect what actually ran, then recover forward — never restore from backup.**
- *Schema changes:* `python migrations/run_migrations.py status` reads the `schema_migrations`
  table, the single source of truth for which versions actually committed. Each version's SQL
  and its `schema_migrations` row change happen in one transaction, so a crash mid-file can
  never leave a version marked "applied" that only half-ran.
- *The backfill:* progress is just `SELECT count(*) FROM orders WHERE currency IS NULL` —
  if a crash happens mid-backfill, re-running `backfill_currency.py` (no flags) continues from
  there and finishes. `migrations/tests/test_migrations.py` proves this by simulating a crash
  (`--max-batches 1`) and then resuming to completion.

**Reversible.** Every migration has a down file: `python migrations/run_migrations.py down
<version>` drops the constraint (`0002`) or the column (`0001`) — both cheap, instant DDL
operations with no data-loss risk, since nothing downstream depends on `currency` yet by the
time you'd choose to roll back.

## Observability

`app/observability.py` wires up all three pillars, kept out of `app/main.py` so the business
logic stays focused:

- **Structured logs.** Every log line is a single JSON object on stdout (`timestamp`, `level`,
  `message`, plus `request_id` and `trace_id`), via a custom `logging.Formatter` + `Filter`. A
  request-scoped `request_id` is generated per request (also echoed back as `X-Request-ID`), and
  `trace_id` is pulled from the active OpenTelemetry span, so a log line and its trace always
  correlate — grep one, find the other. The one deliberate failure path in the app (`/health`
  when the DB is down) logs a structured `db_unavailable` warning before returning 503.
- **Metrics.** `GET /metrics` exposes Prometheus text format: `http_requests_total` (counter,
  labelled `method`/`path`/`status`) and `http_request_duration_seconds` (histogram, same
  labels). That's enough to derive request rate, error rate, and latency distribution.
- **Traces (bonus).** OpenTelemetry auto-instruments FastAPI and `psycopg`, so every request
  gets a span with a nested DB-query span, printed as JSON via a `ConsoleSpanExporter` — no
  collector needed for this demo. This cost ~4 extra dependencies in `app/requirements.txt`, a
  deliberate tradeoff against the "lean image" goal from the containerisation task, made because
  the trace→log correlation is worth it for debugging a real incident.

**The alert I'd set:** sustained HTTP 5xx rate above 5% over a 5-minute window
(`observability/alerts.yml`, a concrete — if unwired, since there's no cloud here — Prometheus
rule). It's actionable (DB down, a bad deploy, or a migration that broke the app all show up this
way) and it means something is actually broken for users right now, not just "an error happened
once."

**The alert I would *not* set:** raw 4xx counts, or latency percentiles, as a standalone trigger.
4xx naturally includes expected, non-actionable noise — we've already seen `GET /` and
`GET /favicon.ico` return 404 in completely normal `docker compose` operation (browsers probing
for a favicon, nothing wrong with the service) — and on this service's low, bursty traffic a p99
latency alert would mostly fire on sample-size noise rather than a real regression. Either one
as a page would train whoever's on call to ignore the pager.

**Mapping to Azure:** structured stdout logs → Azure Monitor Log Analytics (via the Container
Apps/AKS log driver); `/metrics` → Azure Monitor managed Prometheus (or App Insights custom
metrics) scraping the same endpoint; traces → swap the `ConsoleSpanExporter` for an OTLP exporter
pointed at Application Insights' distributed tracing, with `request_id`/`trace_id` carrying
straight through so logs and traces still correlate in Log Analytics.

---

# Case Study: DevOps / Platform Engineer

**Overview**

Well done on getting through to our case study interview! This role is the platform seat in Lula's R&D pod — a small team that ships fast into production. The most common failure point when we move quickly isn't the idea or the code, it's operational reality: broken deployments, environment drift, unsafe database changes, infrastructure that blocks promotion to production. This role owns that path — from what the pod builds to what the business can safely run.

This case study is a hands-on preview of exactly that: take a service from "runs on my machine" to "safe to run in production" — containerised, deployed through a pipeline, with a database change shipped safely, and enough observability to diagnose it when it breaks. We care about **judgment and ownership**, not a polished product.

**Objectives**

*Part 1 — Build (~3 hours).* The app is deliberately trivial; the platform work is the point. **The safe schema migration is the centrepiece — get that right first.** The container, pipeline and observability need only be good enough to demonstrate your approach; we'd rather see a solid, well-reasoned migration than four half-finished pieces.

- **Containerise the app** — a lean, multi-stage, non-root Dockerfile, and add your `app` service to `docker-compose.yml` so `docker compose up` runs the whole thing.
- **A CI/CD pipeline** (GitHub Actions — runs on your repo's free runners when you push, no cloud account needed) that builds the image, runs tests, **and runs the database migration** against the **ephemeral Postgres service container** in the CI job. That CI run *is* the "deploy" target — nothing goes to a real cloud.
- **The schema migration (the heart of it).** Evolve the baseline `orders` table with a change that's **safe under live traffic**: backwards-compatible, **expand/contract**, reversible. Then handle the **mid-run-failure path** — if it half-applies, how do you detect what actually ran and recover? (Restoring from a backup is not the answer we're after.)
- **Observability.** Instrument the service with at least one **metric** and **structured logs** (a **trace** is a bonus), and decide **one alert you'd set and why** — and one you'd *not* set because it'd be noise.

*Part 2 — Present & defend (in the session).* Walk us through what you built and **why**: the migration-safety decisions, the mid-run-failure playbook, how you'd map it to **Azure** for real (AKS / Container Apps, Azure SQL, Azure DevOps, Key Vault), and **how you used AI tools** — what you accepted and what you overrode. Expect a live technical deep-dive.

**Instructions**

- ~3 hours from your first commit. Commit regularly — we read the history. If you run short, prioritise the migration and note what you'd have done next.
- **Use AI tools** (Cursor, Claude, Copilot) — we expect it and want to see how you work with them.
- **Submit** your GitHub repo link **24 hours before** your session. Please make the repo **public for the review** (you're welcome to set it back to private afterwards), plus a short **screen recording (5-10 min)** walking through what you built, the migration-safety decisions, and how you used AI.

We look forward to discussing your response. Good luck, and please reach out to your Talent Partner, Andrea (andrea.louw@lula.co.za), should you have any questions.
