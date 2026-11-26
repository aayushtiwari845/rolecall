# Deploying Rolecall for free

Two options. Both cost nothing to run.

## Option A: Oracle Cloud Always Free VM + Vercel (recommended)

Oracle's Always Free tier includes an Ampere A1 ARM VM with up to 4 cores and 24 GB RAM,
enough for Postgres, the API, the worker and the embedding model. Sign-up asks for a card
to verify identity; Always Free resources are not charged unless you upgrade the account
to pay-as-you-go yourself.

1. **Create the VM** (Ubuntu 22.04+, Ampere A1, 2–4 OCPU, 12–24 GB). In the VCN security
   list, allow inbound TCP 80 and 443. Home region availability varies; if Mumbai is out
   of capacity, Hyderabad or Singapore work fine.
2. **Install Docker** on the VM:
   ```bash
   curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker $USER
   ```
   Open the ports in the OS firewall too: `sudo iptables -I INPUT -p tcp -m multiport --dports 80,443 -j ACCEPT`.
3. **Pick a hostname** for the API. Free options: `<vm-ip>.sslip.io` (no sign-up) or a
   DuckDNS subdomain. Caddy gets a Let's Encrypt certificate for it automatically.
4. **Configure and start**:
   ```bash
   git clone <your repo> rolecall && cd rolecall
   cp .env.example .env
   # set: ENV=production, POSTGRES_PASSWORD, JWT_SECRET (long random), API_DOMAIN,
   #      WEB_URL=https://<your-app>.vercel.app, GOOGLE_CLIENT_ID/SECRET, ADMIN_EMAILS,
   #      any LLM keys, SMTP settings for digests
   docker compose -f infra/docker-compose.prod.yml --env-file .env up -d --build
   ```
   The worker seeds the companies and starts crawling within a minute. The first full
   crawl takes about half an hour; embeddings follow every 10 minutes.
5. **Deploy the web app on Vercel**: import the repo, set the root directory to `web`, and
   add the environment variable `API_URL=https://<API_DOMAIN>`. Vercel proxies `/api/*` to
   the VM, so the session cookie stays first-party on the Vercel domain.
6. **Google sign-in**: in Google Cloud Console create an OAuth client (Web application)
   with the authorised redirect URI `https://<your-app>.vercel.app/api/auth/google/callback`.
   Put the client id and secret in `.env` and restart the API.

Backups: the `backup` service writes a `pg_dump` per weekday into `infra/backups/`.
Oracle may reclaim Always Free instances that stay idle for a week; the crawler keeps the
VM busy enough to avoid that.

## Option B: no card at all

- **Database**: Neon free tier (Postgres with pgvector, 0.5 GB). Run
  `uv run alembic upgrade head` against it once.
- **API**: Render, Koyeb or Hugging Face Spaces free tier using `backend/Dockerfile`
  (cold starts after idle; the embedding model is baked into the image).
- **Ingestion**: GitHub Actions. Set the repo secret `DATABASE_URL` (plus LLM keys) and
  the repository variable `INGEST_ON_ACTIONS=true`; `.github/workflows/ingest.yml` then
  crawls, embeds and enriches every 4 hours on free runners.
- **Web**: Vercel as above.

## Free LLM keys

Any subset works; the router falls through in order.
- Groq: console.groq.com → API keys.
- Google Gemini: aistudio.google.com → Get API key.
- Cerebras: cloud.cerebras.ai.
- OpenRouter: openrouter.ai (use models ending in `:free`).
- Local: `ollama pull qwen2.5:7b` and set `OLLAMA_BASE_URL=http://localhost:11434/v1`
  (useful for batch enrichment from a laptop GPU).

## Email digests

Any SMTP server. The simplest free option is a Gmail account with an app password
(`SMTP_HOST=smtp.gmail.com`, port 587). Brevo's free tier also works.

## Keeping it running for years

Most of the upkeep is automatic. The worker (or, card-free, the `Ingest` and
`Maintenance` workflows) does:

| What | When | Why |
|---|---|---|
| Crawl every board not crawled in the last 5 hours | every 2 h | each board is checked about 4 times a day |
| Embed new and changed roles | every 10 min | search and feeds see new roles quickly |
| Prune | daily | closed roles nobody acted on go after 180 days, their vectors after 30; impressions after a year; logs and the LLM cache after 90 days, so the free database never fills up |
| Health check | daily | emails `ADMIN_EMAILS` if no crawl has succeeded in a day, over a quarter of boards fail, or the index is empty |
| Discovery | weekly | re-probes companies whose boards broke (they switched ATS or renamed the slug), companies seen only in hiring threads and aggregators, and new lines in `seeds/candidates.txt`; new boards go straight into the database |

Built-in safety nets:

- A board that suddenly lists nothing, or under 20% of its open roles, is marked
  `suspect` and closes nothing. An ATS API change cannot wipe out a company's roles.
- A board that returns 404 five runs in a row is disabled; discovery re-enables it if
  it comes back.
- An LLM provider that retires a model name is skipped for 6 hours and the log names
  the setting to change (`LLM_MODELS`); the other providers carry on.
- Dependabot opens one grouped update PR a month per ecosystem; CI runs the full test
  suite, including the database tests, on each.

What still needs a human, now and then:

- **Point an uptime monitor at `/api/health/index`** (UptimeRobot or Healthchecks.io
  free tiers). It returns 503 when crawling has stalled.
- **Copy backups off the VM.** The `backup` service keeps seven daily dumps on the same
  disk, which does not survive losing the VM. A weekly
  `rclone copy infra/backups remote:rolecall` to any free storage covers that.
- **Rules changes.** After editing `app/enrich/rules.py`, bump `RULES_VERSION`; the next
  crawl re-enriches changed roles and `rolecall reenrich` re-enriches the rest.
- **Changing the embedding model** needs a migration (the vector size is part of the
  schema) and a full `rolecall embed` afterwards; resumes are re-embedded on next upload.
- **Coverage.** Boards on Greenhouse, Lever, Ashby, Workable, SmartRecruiters and
  Recruitee are crawled in full. Workday tenants (most large enterprises) throttle
  automated clients heavily, and Google, Microsoft and Amazon run their own portals, so
  those are not covered; LinkedIn, Naukri and Indeed forbid crawling and are never used.
  Add companies to `seeds/candidates.txt`; weekly discovery picks them up.
