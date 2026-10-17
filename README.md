# Saqi

Daily irrigation advice per farm block. The FAO-56 engine in `engine/` does all the maths;
the web page only displays it. See `AGENTS.md` and `docs/`.

## Run it

```
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -e .
uvicorn api.main:app --reload
```

Open http://127.0.0.1:8000 on this computer. To open it on a phone on the same Wi-Fi, run
`uvicorn api.main:app --host 0.0.0.0` and browse to `http://<this-computer's-IP>:8000`.

Farms load from `farms/*.yaml` (if any), otherwise `examples/*.yaml`. Copy an example to
`farms/` to add a real pilot farm. The pilot log is written to `data/pilot_log.csv` (not committed).
If `DATABASE_URL` is set, the same log is stored in Postgres instead.

## Chat

Copy `.env.example` to `.env`. Option A is Claude: set `ANTHROPIC_API_KEY` (from
console.anthropic.com; API usage is billed separately from a Claude.ai plan). Option B is
DeepSeek through the Anthropic-compatible endpoint, with no code changes. Option C is Gemini's
free tier, or any OpenAI-format API: set `SAQI_PROVIDER=openai`, `OPENAI_API_KEY`,
`OPENAI_BASE_URL` (Gemini: `https://generativelanguage.googleapis.com/v1beta/openai/`) and
`SAQI_MODEL` (Gemini free tier: `gemini-3.8-flash`). Restart uvicorn and an "Ask Saqi" panel
appears under the plan. Without a key the page works as before and the chat stays hidden. The
model only reads engine numbers through tools (`api/assistant.py`) and can log irrigation the
farmer reports.

## API

- `GET /api/farms`
- `GET /api/farms/{farm}/plan` — today, the previous 7 days and the next 6, per block
- `POST /api/farms/{farm}/blocks/{block}/log` — `{date, runtime_h | gross_mm, note}`
- `GET /api/farms/{farm}/log` — logged irrigation next to what was recommended
- `GET /api/assistant` — whether chat is on
- `POST /api/farms/{farm}/chat` — `{messages: [{role, content}], lang}`
- `GET /healthz` — `{"ok": true}`, for uptime pings. Never asks for the access code.
- `POST /api/login` — `{code}`. Used only when `SAQI_ACCESS_CODE` is set; sets an HttpOnly cookie.

If `SAQI_ACCESS_CODE` is set, every `/api` route requires that code in the `X-Saqi-Code` header
or in the cookie from `POST /api/login`. The page asks for it once and keeps it in the browser.
Without the variable, the API stays open.

## Deploy

The page can run as one free [Render](https://render.com) web service, with the pilot log in
[Supabase](https://supabase.com) Postgres. `render.yaml` is the blueprint.

1. In Supabase: **Connect** → copy the **Session pooler** connection string, the IPv4 one
   (host `*.pooler.supabase.com`, port **5432**). Put that string in `DATABASE_URL`.
   The direct host (`db.<project>.supabase.co`) is IPv6-only, and a free Render instance cannot reach it.
2. In Render: **New** → **Blueprint**, and select this repo. Render reads `render.yaml`
   (Python 3.12, `pip install -e .`, uvicorn on `$PORT`).
3. When Render asks, set the environment variables. `SAQI_ACCESS_CODE` is the shared code for
   the farm page. `DATABASE_URL` is the pooler string from step 1. For Ask Saqi, also set
   `SAQI_PROVIDER`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `SAQI_MODEL`, and `SAQI_FALLBACK_MODEL`.
   Leave a chat variable blank if you are not using that provider.
4. Open the service URL. The page asks for the access code, then works like it does locally.
   Saqi creates the `pilot_log` table on startup if it is missing.
5. Optional: point a free uptime monitor at `https://<service>.onrender.com/healthz` every
   10 minutes. That ping does not need the access code, and it keeps the free instance from sleeping.

## CLI

```
python -m engine.cli --farm examples/bekaa_potato.yaml [--backfill-from YYYY-MM-DD]
```

## Tests

```
pytest
ruff check .
```

### Weather sync (needed on Render)

Open-Meteo limits requests per IP, and Render's free tier shares IPs with other apps,
so the deployed app reads weather from the `weather_daily` table instead of calling
Open-Meteo directly. A GitHub Action (`.github/workflows/sync-weather.yml`) fills it
every 3 hours:

1. GitHub repo → Settings → Secrets and variables → Actions → New repository secret:
   `DATABASE_URL`, same value as on Render.
2. Actions → Sync weather → Run workflow (fills the table straight away).

The app still calls Open-Meteo live if the table is missing or older than 12 h, and
falls back to the stored weather (with a "Weather updated X h ago" note) if that fails.

## Satellite monitoring (Sentinel-2)

Each block with a `boundary` (a GeoJSON Polygon in `[lon, lat]`, drawn on geojson.io) gets:
crop vigour (NDVI), leaf moisture (NDMI), their 2-4 week trend, field evenness, warning flags,
a 90-day trend line and an NDVI colour map. The chat can read it through `get_field_health`.
Thresholds are in `engine/data/satellite.yaml` (rules of thumb, `verify: true`). The
NDVI-based Kc estimate is shown to the chat for comparison only; the water balance does not use it.

Setup (free):
1. Create an account at dataspace.copernicus.eu, then in the Sentinel Hub dashboard create an
   OAuth client. Copy its client ID and secret.
2. GitHub repo → Settings → Secrets and variables → Actions: add `SH_CLIENT_ID` and
   `SH_CLIENT_SECRET` (`DATABASE_URL` is already there).
3. Actions → Sync satellite → Run workflow. The first run backfills 120 days per block; after
   that it runs daily. Render needs no new variables: the app reads what the job stored.

Sentinel-2 pixels are 10 m, so plots under about 0.5 ha give rough readings (the page says so).
