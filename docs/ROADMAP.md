# Roadmap & prompt queue

How we work: JT runs each prompt below in a fresh Cursor agent (Grok for routine work).
When the agent has pushed, JT tells Claude "done" and Claude reviews the latest commit.
Claude handles spec, maths/agronomy review, and the Claude-layer design (phase 3).

## Status
- [x] Spec + AGENTS.md
- [x] Prompt 1: engine core (FAO-56 water balance, tests) — maths reviewed by Claude
- [x] Prompt 2: weather + CLI
- [x] Prompt 3: sanity check → docs/SANITY.md (Claude reviews)
- [ ] Dad call: confirm crop/soil values, Agrimatco system specs, 2–3 pilot farms → update engine/data
- [x] Prompt 4: minimal API + continuous balance + runtime cap (built by Claude)
- [x] UI: mobile farm page in web/ (AR/FR/EN, today + 7 days, soil-water column, explanation, pilot log)
- [x] Claude layer: farm chat in AR/FR/EN with engine tools (get_plan, get_history, log_irrigation); offline fixed-text explanation stays as fallback
- [ ] Test the chat with a real API key: Lebanese-dialect questions, "سقيت ساعتين" logging, out-of-scope questions (pests), trick questions ("roughly how much next month?")
- [ ] Deploy on Render (blueprint in render.yaml) so the page works on a phone in Lebanon
- [ ] Dry run on real pilot farm coordinates before flying (1 Nov 2026)

## Trip MVP scope (before 1 Nov 2026)
In: calibrated engine, mobile page per farm, "Why?" explanation, pilot log (planned vs actual).
Out until after the trip: Supabase/auth, full chat, WhatsApp automation (forward daily recs manually during pilot), dashboard extras.

## Later
- [ ] Supabase + auth + daily scheduled job
- [ ] Chat: what-if tool ("what if I skip today?") computed by the engine
- [ ] WhatsApp daily message + "done 2h" logging
- [x] Sentinel-2 field monitoring: NDVI/NDMI trend, evenness, flags, NDVI map, chat tool (Oct 2026)
- [ ] Draw real block outlines for pilot plots; validate satellite flags against field walks
- [ ] Use NDVI-based Kc in the engine (after comparing with the textbook Kc for a few weeks)
- [ ] Soil sensors, deficit irrigation

## Prompt 2: weather + CLI
```
Read AGENTS.md and docs/SPEC.md. engine/ already exists and is tested.
Add engine/weather.py: fetch daily et0_fao_evapotranspiration and precipitation_sum from Open-Meteo forecast (past_days=7, forecast_days=7) and archive API (date range). Use httpx, simple file cache in .cache/ keyed by lat/lon/date range. Return list of DailyInput.
Add examples/bekaa_potato.yaml (farm near Zahle, lat 33.85 lon 35.90, one potato block on loam, drip 1.6 L/h emitters, 0.3 m emitter spacing, 0.9 m lateral spacing, planted 60 days ago) and examples/coast_citrus.yaml (near Damour, citrus, micro-sprinkler).
Add engine/cli.py: `python -m engine.cli --farm examples/bekaa_potato.yaml [--backfill-from YYYY-MM-DD]` prints a table per block: date, ET0, rain, Kc, ETc, Dr, RAW, irrigate?, gross mm, runtime h:mm. Past days flagged as observed, future days as forecast.
Mock HTTP in tests (no network in pytest). Follow the definition of done in AGENTS.md.
```

## Prompt 3: sanity check
```
Read AGENTS.md. Run the CLI on both example farms with --backfill-from set to 90 days ago.
Write docs/SANITY.md: for each block, total ETc over the period, total gross irrigation recommended, number of irrigation events, average interval between irrigations. Compare against typical seasonal water use for potato and citrus in Lebanon / Mediterranean (cite FAO or other sources in the doc). Flag anything implausible (e.g. irrigating daily on clay, runtime > 12 h, zero irrigation in summer) and fix the engine if it's a bug, not a data issue. List any data values you think are wrong under "Questions for agronomist". Follow the definition of done in AGENTS.md.
```

## Prompt 4: minimal API
```
Read AGENTS.md and docs/SPEC.md. engine/ and the CLI exist and are tested.
Add api/ with FastAPI (add fastapi + uvicorn to pyproject). No database: farms load from examples/*.yaml (or farms/*.yaml if present).
Endpoints:
- GET /farms -> list of farms (id = yaml file stem, name, lat, lon, blocks summary).
- GET /farms/{farm_id}/plan -> for each block: today's DailyResult plus 7-day forecast and 7 past days. Run ONE continuous balance: archive weather from planting_date (perennials: season start, max 365 days back) through yesterday, then forecast today..today+6, starting Dr=0 at the first day. Today's recommendation must come from that full history, not a 7-day window. Put this in engine/ (e.g. engine/plan.py) and make the CLI use it too, so CLI and API share one code path.
- For past days: if a pilot log entry exists, use the logged irrigation as irrigation_applied_mm; otherwise assume the recommendation was followed (current simulate_plan behaviour). Return a flag per day saying which. Include all reason fields (et0, kc, etc, peff, dr, raw, taw) so the UI and LLM never compute numbers.
- POST /farms/{farm_id}/blocks/{block}/log {date, irrigated_mm or runtime_h, note} -> append to data/pilot_log.csv (create if missing; gitignore data/). Logged irrigation feeds back into the balance via the rule above.
- GET /farms/{farm_id}/log -> logged entries with the recommendation made for that day alongside (planned vs actual).
Enable CORS for localhost. Tests with FastAPI TestClient and mocked weather. Document the run command in README.md. Follow the definition of done in AGENTS.md.
```

## Open questions for Dad
See the end of docs/SPEC.md and "Questions for agronomist" in docs/SANITY.md. Added since:
- Longest set a farmer will run per system (max_runtime_h, now a guessed 8 h for drip / micro / sprinkler).
- Citrus now refills over ~5 days of 8 h sets about once a month. Do coastal orchards really run like that, or every 2–4 days with smaller doses? (Answer sets citrus p / management depletion.)
- Micro-sprinkler efficiency (0.85 guessed) and the real flow/spacing on coastal citrus.
