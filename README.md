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

## CLI

```
python -m engine.cli --farm examples/bekaa_potato.yaml [--backfill-from YYYY-MM-DD]
```

## Tests

```
pytest
ruff check .
```
