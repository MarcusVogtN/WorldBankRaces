# Dataset ideas for World Bank race videos

The pipeline (`run.py` + `races/`) accepts any World Bank indicator via `config.json::source.indicator`, with three render modes:

- **Total** — country-level absolute values. Good for "who's biggest" stories.
- **`per_capita: true`** — divides by `SP.POP.TOTL`. Good for "fair fight" stories where small countries can win.
- **`accumulated: true`** — running cumsum across the timeframe. Good for "stock vs flow" stories (cumulative emissions, cumulative aid).

A good chart-race needs: (1) a long enough timeframe for rank churn (≥40 years ideal), (2) at least one dramatic story beat the audience already half-knows (USSR collapse, China's rise, 2008, COVID, oil shocks), and (3) a winner that isn't obvious from frame 1.

---

## 1. Money & power

| Idea | Indicator | Mode | Hook |
|---|---|---|---|
| **GDP race** | `NY.GDP.MKTP.CD` | total | The classic. China overtaking Japan (2010) and closing on the US is the spine. |
| **GDP per capita** | `NY.GDP.PCAP.CD` | per_capita | Tiny rich countries dominate (Luxembourg, Qatar, Switzerland). Flags rotate constantly. |
| **Foreign exchange reserves** | `FI.RES.TOTL.CD` | total | China's reserves explosion post-2000 is jaw-dropping. Japan, Switzerland, Saudi rotate. |
| **External debt stocks** | `DT.DOD.DECT.CD` | total | Developing-country debt story. Argentina/Turkey/Brazil drama. |
| **Inflation, consumer prices** | `FP.CPI.TOTL.ZG` | total (rate) | Hyperinflation parade — Zimbabwe, Venezuela, Argentina. Chaotic, gets attention. |
| **Remittances received** | `BX.TRF.PWKR.CD.DT` | total | India + Mexico + Philippines fight. Per-capita flips it to small islands (Tonga, Tajikistan). |

## 2. People

| Idea | Indicator | Mode | Hook |
|---|---|---|---|
| **Population** | `SP.POP.TOTL` | total | Slow but powerful — China vs India crossover (~2023) is the climax. |
| **Urban population** | `SP.URB.TOTL` | total | China's urbanization is the story; B-side to the population race. |
| **Life expectancy** | `SP.DYN.LE00.IN` | total (rate) | Japan dominates; Soviet collapse visible as a *drop* in Russia. COVID dip in 2020–21. |
| **Net migration** | `SM.POP.NETM` | total | Volatile, signed values — would need rendering tweaks. |
| **Refugees by country of asylum** | `SM.POP.REFG` | total | Pakistan / Iran / Turkey / Germany shifts — each spike maps to a war. |

## 3. Tech & innovation

| Idea | Indicator | Mode | Hook |
|---|---|---|---|
| **Internet users (% pop)** | `IT.NET.USER.ZS` | total (%) | The 1995→2020 climb. Iceland / Nordics dominate early; Gulf states leapfrog. |
| **Mobile cellular subscriptions** | `IT.CEL.SETS` | total | China + India pull away post-2005. Per-capita: UAE, HK weirdness (>200%). |
| **Patent applications, residents** | `IP.PAT.RESD` | total | Japan dominates 80s–00s, then China overtakes everyone in the 2010s. Strong arc. |
| **R&D expenditure (% GDP)** | `GB.XPD.RSDV.GD.ZS` | total (rate) | Israel + South Korea lead; "small countries punching up" story. |
| **High-tech exports ($)** | `TX.VAL.TECH.CD` | total | China's rise is brutal; Germany / Japan / US fight for second. |

## 4. Energy & climate

| Idea | Indicator | Mode | Hook |
|---|---|---|---|
| **CO2 emissions** | `EN.ATM.CO2E.KT` | total + accumulated | **Two videos.** Total = current race (China #1 since 2006). Accumulated = "who actually caused this" — US dwarfs everyone for decades. The contrast is the point. |
| **CO2 per capita** | `EN.ATM.CO2E.PC` | per_capita | Qatar, Trinidad, Kuwait dominate — flips the climate narrative. |
| **Renewable energy share** | `EG.FEC.RNEW.ZS` | total (rate) | Africa + Nordics on top for different reasons; Iceland/Norway/Costa Rica visible. |
| **Energy use per capita** | `EG.USE.PCAP.KG.OE` | per_capita | Iceland, Qatar, Trinidad. Small population × heavy industry. |
| **Forest area (km²)** | `AG.LND.FRST.K2` | total | Russia, Brazil, Canada, US, China — the Brazil decline post-2000 is grim and visible. |

## 5. Trade & connectedness

| Idea | Indicator | Mode | Hook |
|---|---|---|---|
| **Goods exports** | `NE.EXP.GNFS.CD` | total | China's takeoff post-WTO (2001). Germany's persistence. |
| **FDI net inflows** | `BX.KLT.DINV.CD.WD` | total | Volatile — China, US, UK, then surprise hosts (Luxembourg, Ireland for tax reasons). |
| **International tourism arrivals** | `ST.INT.ARVL` | total | France / Spain / US fight. COVID 2020 cliff is visceral. |
| **Air transport, passengers carried** | `IS.AIR.PSGR` | total | Same COVID cliff, plus China's ascent. |
| **Container port traffic (TEU)** | `IS.SHP.GOOD.TU` | total | Shorter timeframe (2000+), but China + Singapore + Korea is a clean story. |

## 6. Health & education

| Idea | Indicator | Mode | Hook |
|---|---|---|---|
| **Health expenditure per capita** | `SH.XPD.CHEX.PC.CD` | per_capita | US runs away with it — already a meme. The "and yet…" contrast is the hook. |
| **Physicians per 1,000 people** | `SH.MED.PHYS.ZS` | total (rate) | Cuba, Greece, Georgia at top — counterintuitive winners. |
| **Government education spending (% GDP)** | `SE.XPD.TOTL.GD.ZS` | total (rate) | Cuba, Nordics, Saudi at various points. |
| **Out-of-pocket health spending (% of total)** | `SH.XPD.OOPC.CH.ZS` | total (rate) | Inverse story — winners are "worst" outcomes. Sudan, Nigeria, Bangladesh climb. |

## 7. Conflict & security (siblings to the military spending video)

| Idea | Indicator | Mode | Hook |
|---|---|---|---|
| **Military spending per capita** | `MS.MIL.XPND.CD` | per_capita | **Already shipped.** |
| **Armed forces personnel** | `MS.MIL.TOTL.P1` | total | China + India + US + N. Korea + Russia. Different story than $ spending. |
| **Arms exports (SIPRI via WB)** | `MS.MIL.MEXP.UN` | total | US / Russia / France / China oligopoly; cumulative version is wild. |
| **Military spending (% of GDP)** | `MS.MIL.XPND.GD.ZS` | total (rate) | Saudi, Israel, Oman, Singapore at the top. Reframes "who cares most." |

---

## Top 5 if you want a shortlist

1. **CO2 emissions — accumulated** (moral-accounting twist; pairs with a total-emissions video as a duo)
2. **GDP per capita** (always-shifting flags; Luxembourg/Qatar/Norway story)
3. **Foreign exchange reserves** (China's rise is unmissable; one-clear-villain narrative)
4. **Patents (residents)** (Japan→China handoff is a cleaner arc than GDP itself)
5. **International tourism arrivals** (built-in COVID cliff)

---

## How to execute any of these

Edit `config.json` only:

1. `source.indicator` → the code from the table above.
2. `source.timeframe` → most indicators have ~1960–2023 coverage; some (internet, container traffic) start later.
3. `video_title` → human-readable title.
4. `output_filename` → `<topic>_race.mp4`.
5. `per_capita` / `accumulated` → match the recommended mode.
6. `trend_label` (and `_per_capita` / `_accumulated` overrides) → label above the sparkline.
7. `value_format` → `"currency"` for $-denominated, anything else for raw numbers.

Then:

```bash
python run.py --refetch        # pulls the new indicator + flags
python run.py --extract-movers # candidate spotlight events for hand-curation
python run.py                  # render
```

## Previewing before committing to a full render

```bash
python run.py --preview-frame 1995
python run.py --preview-frame 2010
python run.py --preview-frame 2023
```

Three frames spanning the timeframe will tell you if the race has visible motion at all phases. If two of the three look identical, the dataset is too flat — pick another.
