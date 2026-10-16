# Spec — AI irrigation advisor

## Goal
Daily, per-block irrigation recommendation for a farm: "Block 2: 18 mm, run drip 3 h 20 min today", plus a chat that explains why.
Target first pilots: farms in Lebanon (Bekaa, coast) using Agrimatco irrigation systems. Languages: Arabic, French, English.
MVP deadline: before Nov 2026 field trip. Success = engine recommendations vs what farmer actually did, over a 4–6 week pilot.

## Data model (MVP)
- **Farm**: name, owner contact (WhatsApp number), lat, lon, timezone.
- **Block**: farm_id, name, area_ha, crop, planting_date, soil_type, system (drip | micro_sprinkler | sprinkler | pivot | surface), system params, optional `kr` canopy factor (orchards).
- **System params (drip)**: emitter_flow_lph, emitter_spacing_m, lateral_spacing_m, efficiency (default 0.90).
- **System params (sprinkler/pivot)**: application_rate_mm_h, efficiency (sprinkler 0.75, pivot 0.85, surface 0.60).
- **DailyState** (per block per day): date, et0_mm, rain_mm, kc, etc_mm, peff_mm, irrigation_applied_mm, dr_mm (end-of-day depletion), recommendation.

## Engine (FAO-56 single crop coefficient, daily root-zone water balance)
1. **Kc by day**: crop has stage lengths L_ini, L_dev, L_mid, L_late (days) and Kc_ini, Kc_mid, Kc_end.
   - ini: Kc_ini; dev: linear Kc_ini→Kc_mid; mid: Kc_mid; late: linear Kc_mid→Kc_end. Perennials: stages are relative to season start date.
2. **ETc** = ET0 × Kc × kr (kr default 1.0; for young orchards under drip, kr < 1).
3. **Effective rain**: P < 5 mm → 0; else Peff = 0.8 × P. (Simple FAO rule; keep it swappable.)
4. **Soil**: TAW = 1000 × (θFC − θWP) × Zr  [mm];  RAW = p × TAW.  Zr = crop root depth (grows linearly from Zr_min at planting to Zr_max at end of dev for annuals).
5. **Depletion**: Dr_i = clamp(Dr_{i-1} − Peff_i − I_i + ETc_i, 0, TAW). Start Dr_0 = 0 (field capacity) unless given.
6. **Trigger**: if forecast Dr for today ≥ RAW → irrigate. Net depth = Dr (refill to field capacity). MVP: full refill; later: deficit strategies.
7. **Gross depth** = net / efficiency.
8. **Runtime**: drip application rate (mm/h) = emitter_flow_lph / (emitter_spacing_m × lateral_spacing_m). runtime_h = gross_mm / rate. Sprinkler/pivot: gross / application_rate_mm_h.
9. **Output** per block per day: irrigate (bool), net_mm, gross_mm, runtime_h, dr_mm, raw_mm, taw_mm, reason fields (et0, kc, etc, peff) so the LLM can explain without inventing.

## Weather — Open-Meteo (no API key)
- Forecast: `https://api.open-meteo.com/v1/forecast?latitude=..&longitude=..&daily=et0_fao_evapotranspiration,precipitation_sum,temperature_2m_max,temperature_2m_min&timezone=auto&past_days=7&forecast_days=7`
- Backfill: `https://archive-api.open-meteo.com/v1/archive` same daily vars with start_date/end_date.
- Cache responses (per lat/lon/date) to avoid refetching.

## Reference data (FAO-56 defaults — ALL `verify: true`, confirm with Dad)
Soils (θFC, θWP, volumetric): sand 0.12/0.04 · loamy_sand 0.14/0.06 · sandy_loam 0.23/0.10 · loam 0.25/0.12 · silt_loam 0.29/0.15 · clay_loam 0.32/0.20 · clay 0.36/0.22

Crops (Kc_ini / Kc_mid / Kc_end · Zr_max m · p):
- potato 0.50/1.15/0.75 · 0.5 · 0.35
- tomato 0.60/1.15/0.80 · 1.0 · 0.40
- wheat 0.30/1.15/0.30 · 1.2 · 0.55
- table grapes 0.30/0.85/0.45 · 1.5 · 0.35
- citrus (≈70% canopy, no cover crop) 0.70/0.65/0.70 · 1.2 · 0.50
- olive 0.65/0.70/0.70 · 1.5 · 0.65
- avocado 0.60/0.85/0.75 · 0.7 · 0.70
- apple 0.60/0.95/0.75 · 1.2 · 0.50
Stage lengths: use FAO-56 Table 11 Mediterranean values as defaults; Dad to confirm local.

## Phases
1. **Engine + weather + CLI** (now). `python -m engine.cli --farm examples/bekaa_potato.yaml` prints 7-day plan.
2. **API + Supabase**: FastAPI endpoints (farms, blocks, daily recommendation, log actual irrigation), scheduled daily job.
3. **Claude layer + dashboard**: Claude tool-use (`get_recommendation`, `get_block_history`, `log_irrigation`), replies in user's language; Next.js dashboard.
4. **WhatsApp**: daily morning message per farm + farmer replies "done 2h" → logged. (Meta Cloud API or Twilio.)
5. **Later**: Sentinel-2 NDVI stress flags, soil moisture sensors, deficit irrigation.

## Open questions for Dad
- Main crops per region and local Kc / stage lengths
- Typical Agrimatco system specs (emitter flow, spacing, pivot rates)
- How farmers decide today (schedule, gut, agronomist?) and who decides daily
- Water/energy cost per m³; 2–3 pilot farms; Agrimatco's position on the project and farm data
