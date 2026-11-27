# Deploying Rolecall for free

Two options. Both cost nothing to run.

## Option A: Oracle Cloud Always Free VM + Vercel (recommended)

Oracle's Always Free tier includes Ampere A1 (ARM) capacity of **2 OCPUs and 12 GB of
RAM in total** (Oracle cut this from 4 OCPUs / 24 GB in August 2026). That is enough for
Postgres, the API, the worker and the embedding model.

**Staying at zero cost.** Sign-up needs a card for identity checks; Oracle may place a
small temporary authorisation hold that is released. Oracle's terms say the card is not
charged unless you upgrade the account. So:

- Never click **Upgrade to Pay As You Go** (or any paid account type).
- Create only resources labelled **Always Free-eligible**, in your **home region**:
  one A1 VM with at most 2 OCPU / 12 GB, a boot volume of 50 GB (200 GB is free in total).
- The 30-day trial credits can be spent on paid shapes without charge, but anything paid
  is deleted when the trial ends, so don't build on it.
- After the trial, an account that has not upgraded keeps its Always Free resources and
  cannot run paid ones.
- Idle Always Free VMs may be *reclaimed* (stopped), which costs nothing but takes the site
  down: Oracle treats a VM as idle when, over 7 days, CPU (95th percentile), network and
  memory are all under 20%. Check the instance's **Metrics** page after the first week.

Steps:

1. **Create the VM**: Compute → Instances → Create. Image **Ubuntu 24.04** (Always Free
   eligible), shape **VM.Standard.A1.Flex** with **2 OCPU, 12 GB**. Under networking keep
   "assign a public IPv4 address". Upload (or let Oracle generate) an SSH key. If you get
   "out of host capacity", try another availability domain or retry later.
2. **Open ports 80 and 443** in the cloud firewall: Networking → Virtual cloud networks →
   your VCN → Security Lists → Default → Add ingress rules: source `0.0.0.0/0`, TCP,
   destination ports `80,443`.
3. **Deploy the web app on Vercel** (free Hobby plan, no card): import the GitHub repo, set
   the root directory to `web`, deploy, and note the URL, e.g. `https://rolecall-xyz.vercel.app`.
4. **Set up the VM** over SSH (`ssh ubuntu@<vm-ip>`):
   ```bash
   git clone https://github.com/aayushtiwari845/rolecall.git && cd rolecall
   bash infra/bootstrap.sh https://rolecall-xyz.vercel.app
   ```
   It installs Docker, opens the OS firewall (Oracle's Ubuntu image blocks everything but
   SSH), adds swap, writes `.env` with generated database and session secrets and a free
   `<ip>.sslip.io` hostname, then builds and starts the stack. The worker seeds the
   companies and starts crawling; the first full crawl takes about half an hour.
5. **Point Vercel at the API**: Project → Settings → Environment Variables →
   `API_URL=https://<ip-with-dashes>.sslip.io` (the script prints it), then redeploy.
   Vercel proxies `/api/*` to the VM, so the session cookie stays first-party.
6. **Google sign-in**: Google Cloud Console → APIs & Services → OAuth consent screen
   (External; publish it, since email and profile scopes need no review) → Credentials →
   Create OAuth client ID (Web application) with the authorised redirect URI
   `https://rolecall-xyz.vercel.app/api/auth/google/callback`. Put the client id, secret
   and your email in `.env` on the VM (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
   `ADMIN_EMAILS=["you@gmail.com"]`) and re-run `bash infra/bootstrap.sh <vercel url>`.

The API refuses to start in production with a missing or default `JWT_SECRET` or a
localhost `WEB_URL`. Backups: the `backup` service writes a `pg_dump` per weekday into
`infra/backups/` (copy them off the VM; see "Keeping it running" below). If
Let's Encrypt ever refuses a certificate for the shared sslip.io domain, use a free
DuckDNS subdomain as `API_DOMAIN` instead.

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
