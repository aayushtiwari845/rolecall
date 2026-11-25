# Rolecall web

Next.js (App Router, TypeScript, Tailwind CSS v4) front end for Rolecall.

```bash
pnpm install
pnpm dev          # http://localhost:3000, proxies /api/* to API_URL (default http://localhost:8000)
pnpm lint && pnpm exec tsc --noEmit
pnpm build
```

The browser only talks to this origin: `next.config.ts` rewrites `/api/*` to the FastAPI
service, so the session cookie is first-party and no CORS is needed. On Vercel set
`API_URL` to the API's public URL.

Structure:

- `app/` routes: landing, login, onboarding, feed (scorecard), search, jobs/[id], tracker,
  chat, settings, admin, evals, privacy
- `components/` shared UI: the scorecard job row and keyboard-driven list, app shell,
  landing scoreboard and ticker, resume upload, preference form
- `lib/` API client (CSRF header, SSE reader), paginated job lists with optimistic
  updates, formatting, types

Design: the "Scorecard" world. Dark mode is the stadium scoreboard (pitch-black green,
chalk numerals in Big Shoulders, scoreboard amber); light mode is the scorer's book
(cool white, ruled green hairlines). Saved roles get a hand-drawn pen ring, hidden ones
a red strike. See `/DESIGN.md` at the repository root.
