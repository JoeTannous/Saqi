# Sanity check — 90-day CLI backfill

Run on 16 October 2026. The farm clock is `Asia/Beirut`. On that clock the day was 16 October, so 90 days back is 18 July 2026.

```
python -m engine.cli --farm examples/bekaa_potato.yaml --backfill-from 2026-07-18
python -m engine.cli --farm examples/coast_citrus.yaml --backfill-from 2026-07-18
```

Weather is Open-Meteo archive ET0 (`et0_fao_evapotranspiration`) and `precipitation_sum` for 18 July through 15 October (yesterday). A backfill run stops at yesterday; it does not print today or the forecast. Totals below are summed from that same plan, before the table rounds each day to 0.1 mm.

The balance starts at field capacity (`Dr = 0`) on the first day kept for the block. Each day the engine recommends a full refill when depletion reaches RAW, and the plan assumes that net depth was applied. No pilot log overrides that.

The daily water balance closes on both blocks: `ETc − Peff − net irrigation − Dr at the end = 0`. Nothing in the arithmetic was changed. Crop, soil, and system numbers marked `verify: true` were left as they are.

## Zahle potato — Block 1

`examples/bekaa_potato.yaml`. Potato on loam, drip, planted 17 August 2026 (`planting_days_ago: 60`). Emitters 1.6 L/h at 0.3 m, laterals at 0.9 m, so the application rate is 5.93 mm/h. Efficiency 0.90 from `engine/data/systems.yaml`. The archive starts 18 July, and 30 days before planting are omitted. The simulated period is 17 August–15 October: **60 days**, the initial stage plus the first half of development. Mid-season Kc (1.15) is not reached. Kc on 15 October is 1.06. RAW grows from 6.8 mm to 21.5 mm as roots go from 0.15 m toward 0.50 m.

| | |
| --- | --- |
| Total ETc | 167.1 mm (2.8 mm/day) |
| Total gross irrigation | 174.2 mm |
| Net irrigation | 156.8 mm |
| Rain / effective rain | 24.3 mm / 4.1 mm |
| Irrigation events | 11 |
| Average interval | 5.5 days |
| Longest runtime | 4 h 04 min (24.1 mm gross) |

Interval is the mean gap between consecutive irrigation dates (19 Aug, 22 Aug, 25 Aug, 29 Aug, 3 Sep, 8 Sep, 14 Sep, 22 Sep, 29 Sep, 7 Oct, 13 Oct). Gaps start at 3 days and lengthen to 6–8 days as the root zone gets deeper. Runtimes run from 1 h 34 min to 4 h 04 min.

Depletion at the end of 15 October is 6.2 mm, under RAW of 21.5 mm, so the last day does not irrigate.

### Comparison

FAO's crop-information sheet for potato gives a seasonal water requirement of **500–700 mm for a 120–150 day crop**, and describes a shallow root system that wants frequent irrigation. Under demand of 5–6 mm/day, depletion past about 25% of available water starts to cost yield. Source: [FAO Land & Water, Potato](https://www.fao.org/land-water/databases-and-software/crop-information/potato/en/).

167 mm is not that seasonal total. It is the first 60 days of the 145-day stage lengths in `engine/data/crops.yaml` (FAO-56 Table 11, April, Europe: 30/35/50/30). Kc is 0.50 through 15 September and only then climbs. A quarter to a third of the FAO seasonal range, spent before mid-season, is the right magnitude. This run does not test tuber bulking.

Local checks point the same way:

- Bekaa summer reference ET0 in 2020 was about **460–540 mm** (roughly 5–6 mm/day), and early-season potato net irrigation rose from 0–2 mm/day to **6–8 mm/day at the June peak**. Late-season ET0 was lower. Source: Moujabber et al., Remote Sensing 16(9):1598, 2024, [doi:10.3390/rs16091598](https://doi.org/10.3390/rs16091598). Late-August ET0 on this block averaged 5.7 mm/day, inside that summer band. ETc averaged 2.8 mm/day because the crop is not at full cover.
- A spring potato at AREC (Bekaa), 12 March–15 July 2020, used **521 mm**. The applied depth was 590 mm and about 487 mm reached the soil. Sets were every **4–5 days**. Source: Jaafar, Mourad, Hazimeh, and Sujud, Remote Sensing 14(20):5090, 2022, [doi:10.3390/rs14205090](https://doi.org/10.3390/rs14205090). Our 5.5-day mean interval matches that practice. Our gross depth is much smaller because this is only the establishment of an autumn planting.

### Flags

No engine bug on this block.

- Not irrigating every day. The soil is loam, not clay, and the shortest gap is 3 days.
- No runtime over 12 hours.
- Not a dry summer with zero irrigation. The first refill is 19 August, day 3.
- Of 24.3 mm of rain, 19.2 mm fell in days under 5 mm and was ignored. The only counted storm is 5.1 mm on 18 September (effective 4.1 mm). A 4.9 mm day on 28 September was ignored, and the block was irrigated on 29 September. That is the rule in the spec (`P < 5 mm → 0`, else `0.8 × P`), and it is harsh on light Bekaa showers. It is not a code error.

## Damour citrus — Block 1

`examples/coast_citrus.yaml`. Citrus on sandy loam, micro-sprinkler, season start 1 January 2026. All **90 days** (18 July–15 October) are inside the season. Kc is 0.65 through 27 September (mid-season) and 0.66 by 15 October (late season has started; Kc_end is 0.70). Roots stay at 1.2 m. TAW is 156 mm, RAW is 78 mm (`p = 0.50`). The example sets efficiency at 0.85 and the application rate at 2.8 mm/h (one 70 L/h head on a 5 m × 5 m tree).

| | |
| --- | --- |
| Total ETc | 280.1 mm (3.1 mm/day) |
| Total gross irrigation | 279.8 mm |
| Net irrigation | 237.9 mm |
| Rain / effective rain | 62.4 mm / 33.1 mm |
| Irrigation events | 3 |
| Average interval | 32 days |
| Runtime of each event | 33 h 27 min, 33 h 06 min, 33 h 24 min |

Events are 8 August (93.6 mm gross), 4 September (92.7 mm), and 11 October (93.5 mm). The gaps are 27 and 37 days. The longer second gap lines up with a lower ET0 and with rain on 29 August (11.7 mm), 18 September (13.8 mm), 28 September (6.6 mm), and 2 October (9.3 mm). Depletion at the end of 15 October is 9.1 mm.

### Comparison

FAO gives citrus **900–1200 mm per year**, evergreen, and for a clean-cultivated orchard with about 70% canopy the monthly coefficients are 0.65 in June–September and 0.70 in October. From July through autumn, FAO also says depletion of 60–70% of available water is acceptable and irrigation can be less frequent than in the flowering period. Source: [FAO Land & Water, Citrus](https://www.fao.org/land-water/databases-and-software/crop-information/citrus/en/).

280 mm in 90 days sits against that annual range rather than against a 90-day crop. Spread evenly, 900–1200 mm/year is 222–296 mm in 90 days. July–October is a high-demand part of the year, so landing at the top of that slice is plausible. The Kc path (0.65, then edging toward 0.70 in October) matches the FAO monthly table. The volume is believable. The schedule shape is not.

July ET0 on this block averaged 5.7 mm/day and August 5.2 mm/day, the same band as the Bekaa summer figures above. Coastal humidity would often make ET0 a bit lower than the Bekaa; this particular Open-Meteo window does not.

### Flags

**Runtime is about 33 hours on every event.** Gross depth is about 94 mm because the model refills roughly 79 mm of depletion and then divides by efficiency 0.85. At 2.8 mm/h that is 33 hours. The prompt's own implausible case is a runtime over 12 hours. A farmer cannot run one micro-sprinkler set for a day and a half.

This is not a bug in the balance. Net, gross, and runtime follow the spec: irrigate when `Dr ≥ RAW`, net depth equals that depletion, gross = net / efficiency, runtime = gross / application rate. The same identity that closes the potato block closes this one. The dose is large because RAW is 78 mm (1.2 m roots, `p = 0.50`, sandy loam holding 130 mm/m). The set is long because the example rate is 2.8 mm/h. AREC's micro-sprinklers, on the same 5 m × 5 m spacing, were **200 L/h (8 mm/h)**, not 70 L/h (Jaafar et al. 2022, cited above). At 8 mm/h this same 94 mm would be about 12 hours, still a very long set.

**18 July–7 August has no irrigation.** That is the opening assumption, not a summer with no demand. ETc in those 14 July days is 51 mm. Depletion climbs from 0 and first crosses RAW on 8 August. A real orchard on 18 July would not still be at field capacity unless it had just been irrigated or had taken a large rain. The 90-day window does not carry depletion from earlier in the season. Once the cycle is going, the model does irrigate in August, September, and October. It does not irrigate daily, and the soil is sandy loam, not clay.

Light rain under 5 mm (21 mm of the 62 mm total) is discarded, same rule as the potato block.

## Questions for agronomist

These are the values that make the citrus set implausible, or that this window cannot confirm. FAO-56 defaults marked `verify: true` were not edited.

1. **Micro-sprinkler rate in `examples/coast_citrus.yaml` (2.8 mm/h).** It assumes one 70 L/h head per 25 m². The published AREC layout on a 5 m × 5 m grid was 200 L/h. What flow, spacing, and wetted diameter does Agrimatco actually install on coastal citrus, and what is the longest set the farmer will run?
2. **One full refill per trigger.** The spec refills to field capacity in a single day. For this block that is ~80 mm net and ~94 mm gross. Should a recommendation be split across several days once runtime exceeds a limit, and what limit?
3. **Citrus root depth 1.2 m and `p = 0.50`.** They are the FAO-56 defaults and they set RAW at 78 mm. A Mediterranean orchard on a different rootstock can be much shallower (one Sicilian mandarin stand was rooted to about 0.5 m). If Damour trees are shallower, the dose and the runtime both fall. FAO's own citrus page uses about `p = 0.40` in the sensitive period and allows 60–70% depletion from July on, so 0.50 may be slightly frequent for late summer or slightly dry for flowering. Which depletion fraction should a pilot use?
4. **Citrus Kc 0.70 / 0.65 / 0.70.** This is FAO-56 for 70% canopy and no cover crop. FAO's "no weed control" coefficients are about 0.85–0.90. If the floor of the orchard is weedy or covered, these Kc values are low and the 280 mm understates ETc.
5. **Micro-sprinkler efficiency 0.85.** `engine/data/systems.yaml` has no micro-sprinkler row (the spec does not give one). The example picks 0.85, between drip (0.90) and sprinkler (0.75). The AREC catch-can loss was 15–20%. Confirm a figure before any pilot.
6. **Potato stage lengths 30 / 35 / 50 / 30 days.** FAO-56 Table 11 has no Mediterranean potato row; the file uses April, Europe. This example is an August Bekaa planting, and the Bekaa also grows an early (spring) crop whose peak demand is in June. Which calendar is the pilot, and what stage lengths should it use?
7. **Potato `Kc_end` 0.75.** FAO-56 Table 12 uses 0.75, with a footnote that vine-kill can be about 0.40. This 60-day window never reaches late season. Do Bekaa growers kill the vines?
8. **Rain under 5 mm counts as zero.** On the potato block that discarded 19.2 of 24.3 mm, including 4.9 mm the day before an irrigation. Is that the rule you want on Lebanese showers, or should a lower threshold be used?
9. **Textbook soil water contents.** Loam 0.25/0.12 and sandy loam 0.23/0.10 are FAO-56 Table 19. Available water for both is 130 mm/m. The AREC potato trial reported 65 mm in 50 cm of a soil they called clay, which is the same 130 mm/m. A real Bekaa clay or a coastal sand could be quite different. Needs a soil for each pilot farm.
10. **Potato emitter layout (1.6 L/h, 0.3 m, 0.9 m).** The runtimes (1.5–4 h) look like normal drip sets, so nothing here is flagged as wrong. Still needs the Agrimatco layout the pilot farms actually have.
