# AGENTS.md — read this first

Project: **AI irrigation advisor** — name: **Saqi** (ساقي, "the one who waters"). Inspired by ORTH (Aydi), narrowed to irrigation.
Full spec: `docs/SPEC.md`. Read it before any non-trivial change.

## Core rule
The **engine does the maths, the LLM only explains**. Never let Claude/AI generate irrigation numbers.
Every number shown to a farmer must come from deterministic, unit-tested code in `engine/`.

## Stack
- `engine/` — pure Python 3.11+ package, no web deps. FAO-56 water balance. Fully unit-tested (pytest).
- `api/` — FastAPI wrapping the engine. Serves `web/` at `/` and JSON under `/api`. `api/assistant.py` is the Claude layer: system prompt + tools; Claude reads numbers only via tools.
- `web/` — plain HTML/CSS/JS, no build step (trip MVP). Formats API numbers only; never computes irrigation values. AR/FR/EN, Arabic is RTL.
- DB/auth: Supabase (phase 2+). Weather: Open-Meteo (no key). LLM: Claude API with tool use (phase 3).

## Conventions
- Units in every variable name where ambiguous: `et0_mm`, `flow_lph`, `depth_m`, `runtime_h`.
- Type hints everywhere; dataclasses or pydantic models for inputs/outputs.
- Crop/soil/system parameters live in data files (`engine/data/*.yaml`), never hardcoded in logic.
- Values marked `verify: true` in data files are FAO-56 defaults awaiting confirmation from a local irrigation expert. Don't silently change them.
- Small commits, run `pytest` before saying a task is done.
- Secrets in `.env` only (never commit). `.env.example` lists required keys.

## Definition of done (every task)
- Run `pytest` and `ruff check .` until clean.
- Commit with a clear message and push to `main`. Never leave work uncommitted.
- End with a 3-line summary: what changed, how it was tested, anything unverified or assumed.
- Update the status checkboxes in `docs/ROADMAP.md` if the task completes one.
