# Deploying BankOps AI to the web (free tiers)

```
 Visitor's browser
       |
       v
 Vercel  (React UI, static)  --HTTPS /api-->  Render (FastAPI in Docker, free web service)
                                                   |                      |
                                                   v                      v
                                            Neon (PostgreSQL)      Groq (gpt-oss-120b, free tier)
```

| Piece | Service | Free tier notes |
|---|---|---|
| UI | [Vercel](https://vercel.com) | static site, always on |
| API | [Render](https://render.com) web service (Docker) | sleeps after ~15 min idle; first request wakes it in about a minute (the UI shows a "waking up" screen) |
| Database | [Neon](https://neon.tech) PostgreSQL | free project; compute pauses when idle and resumes on first query |
| AI | [Groq](https://console.groq.com) | about 8K tokens/minute and 1K requests/day on `openai/gpt-oss-120b`; the app adds its own daily cap (`AI_DAILY_LIMIT`) |

All four sign up with your GitHub account. Secrets are pasted only into each service's dashboard, never into the repository.

## 1. Groq API key

1. Sign in at https://console.groq.com, then API Keys, then Create API key, and copy it (starts with `gsk_`).
2. Optional local test: put it in `D:\Study\BankOps-AI\.env` as `GROQ_API_KEY=...`, set `AI_PROVIDER=groq`,
   run `docker compose up -d backend`, and run an analysis from the UI.

## 2. Neon database

1. https://neon.tech, then New project, named `bankops-ai`, region close to the Render region (for example EU Frankfurt).
2. Copy the connection string (Dashboard, then Connect). It looks like
   `postgresql://user:password@ep-xxx.eu-central-1.aws.neon.tech/neondb?sslmode=require`.
   The backend converts it to the `postgresql+psycopg://` form automatically.

## 3. Render backend

1. https://render.com, then New, then Blueprint, then connect the GitHub repo `Srinivasand04/bankops-ai`.
   Render reads [`render.yaml`](../render.yaml) and proposes the service `bankops-ai-api`.
2. Fill in the three secret values it asks for:
   - `DATABASE_URL` - the Neon connection string
   - `GROQ_API_KEY` - the Groq key
   - `CORS_ORIGINS` - `["https://<your-vercel-app>.vercel.app"]` (use `["*"]` until the Vercel URL exists, then tighten it)
3. Deploy. On start the container runs the Alembic migrations, resets and loads the demo data
   (`DEMO_RESET_ON_START=true`), and starts the API on Render's port.
4. Check `https://bankops-ai-api.onrender.com/api/health` and `/docs` (Swagger).

## 4. Vercel frontend

1. https://vercel.com, then Add New, then Project, then import `Srinivasand04/bankops-ai`.
2. Root directory: `frontend` (framework Vite is detected; [`vercel.json`](../frontend/vercel.json) sets the
   build and the single-page-app rewrite).
3. Environment variable: `VITE_API_BASE_URL` = `https://bankops-ai-api.onrender.com/api`.
4. Deploy, open the `*.vercel.app` URL, and put that URL into Render's `CORS_ORIGINS` (step 3.2), which redeploys.

## 5. Check the live demo

- The first visit after idle shows "Waking up the demo server" for up to a minute.
- Run an analysis on INC-1012 (see the [user guide](user-guide.md)); with Groq it takes seconds.
- The AI card shows how many demo analyses are left today.

## Public-demo safeguards

| Risk | Safeguard |
|---|---|
| Visitors use up the free AI quota | `AI_DAILY_LIMIT` (25/day in `render.yaml`); Groq's own per-minute limit returns a clear "try again shortly" |
| Visitors leave junk data | demo data resets on every server start (free Render restarts after idle) |
| Anyone can act as the manager | intended for the demo: the "Acting as" switcher shows the role rules; `AUTH_ENABLED=true` with `API_KEYS` turns on API-key auth |
| Real data exposure | the hosted demo only ever contains synthetic data |

This is a showcase deployment, not a production setup: there is no SSO, the demo identity is chosen by the visitor,
and free tiers have no availability guarantee.
