# WorldStatsRaces

En automatiseret pipeline der laver korte YouTube- og X-videoer ud af verdensdata.
Den henter data, tegner en animeret "race"-video hvor lande konkurrerer over tid,
skriver et manuskript, læser det op, sætter musik på og uploader det færdige
resultat — uden at jeg rører ved det undervejs.

> **Søsterprojekt:** `SportStatsRaces` — samme idé, men for fodboldstatistik
> (spillere og hold i stedet for lande). Det ligger i mappen `sportstatsraces/`
> og deler den samme render-motor. Det er stadig under udvikling og laver i dag
> kun videoer uden voiceover.

---

## Hvad er en "race-video"?

Forestil dig et søjlediagram hvor søjlerne skifter plads over tid. Fx:
*"Hvilket land har de rigeste indbyggere fra 1970 til 2023?"* — så ser man
landene rykke op og ned i ranglisten år for år, mens en stemme fortæller hvad
der sker.

Et eksempel ligger i `output/gdp_per_capita_race_narrated.mp4`.

---

## Hvordan virker pipelinen?

Pipelinen er bygget op af en række trin der kører i rækkefølge. Hvert trin har
ét job, og resultatet sendes videre til næste trin.

```
   ┌──────────────────────────────────────────────────────────────────┐
   │                         1.  IDÉ                                  │
   │   Plukker en idé fra ideas.md (fx "rigeste lande siden 1970")    │
   └──────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │                         2.  HENT DATA                            │
   │   Henter tal fra World Bank (eller andre kilder).                │
   │   Henter også flag-billeder af landene.                          │
   └──────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │                         3.  FIND HØJDEPUNKTER                    │
   │   Kigger dataene igennem og finder de øjeblikke hvor noget       │
   │   spændende sker (et land overhaler et andet, en rekord, osv).   │
   └──────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │                         4.  SKRIV MANUSKRIPT                     │
   │   En AI (Claude) skriver et kort manuskript der passer præcist   │
   │   med det der sker på skærmen i hvert sekund.                    │
   └──────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │                         5.  LAV STEMME                           │
   │   Manuskriptet sendes til ElevenLabs der laver en oplæsning.     │
   │   Tidligere oplæsninger gemmes så vi ikke betaler dobbelt.       │
   └──────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │                         6.  TEGN VIDEOEN                         │
   │   Tegner alle frames (30 pr. sekund), animerer søjlerne, sætter  │
   │   flag, tal og titler ind. Resultatet er en mp4-fil.             │
   └──────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │                         7.  LYD PÅ                               │
   │   Lægger oplæsning + baggrundsmusik på videoen. Musikken         │
   │   skrues automatisk ned når stemmen taler.                       │
   └──────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │                         8.  UPLOAD                               │
   │   Sender videoen til YouTube som en privat kladde.               │
   │   Jeg gennemser den og udgiver den manuelt.                      │
   └──────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │                         9.  LÆR AF TALLENE                       │
   │   Henter senere views, watch time osv. fra YouTube og gemmer     │
   │   dem i en lille database, så jeg kan se hvad der virker bedst.  │
   └──────────────────────────────────────────────────────────────────┘
```

Hvert trin kan køres for sig selv. Hvis jeg fx kun vil teste hvordan en video
ser ud, kan jeg stoppe efter trin 6 og hoppe over stemme og upload.

---

## Hvorfor er den bygget sådan?

- **Skiftbare datakilder.** Pipelinen er ligeglad med hvor tallene kommer fra
  — World Bank, en CSV-fil, eller noget jeg scraper. Jeg kan plugge en ny
  kilde ind uden at ændre på selve videomotoren.
- **Skiftbare assets.** Det samme gælder billederne ved siden af hver søjle.
  I dag er det landeflag, men `SportStatsRaces` bruger spillerportrætter
  i stedet — uden at videomotoren skal vide noget om det.
- **Cache overalt.** Data, billeder og oplæsninger gemmes lokalt så jeg
  ikke betaler eller venter på det samme to gange.
- **Tjek undervejs.** Jeg kan tegne et enkelt frame som et billede, før jeg
  bruger 5 minutter på at rendere en hel video. Det gør det hurtigt at se
  om noget ser skævt ud.

---

## Mappestruktur

```
WorldStatsRaces/
├── run.py                  Start her — én kommando styrer det hele
├── config.json             Indstillinger for den aktuelle video
├── ideas.md                Liste over fremtidige video-idéer
├── races/                  Selve videomotoren + verdensdata-pipelinen
│   ├── pipeline.py           Trinene 1-8 hængt sammen
│   ├── render/               Tegner videoen
│   ├── sources/              Henter data (fx World Bank)
│   ├── assets/               Henter flag, fonte, musik
│   ├── narration/            Manuskript + stemme + musik
│   └── youtube/              Upload + analytics
├── sportstatsraces/        Søsterprojekt (fodboldstatistik) — under udvikling
├── cache/                  Gemte data, billeder og oplæsninger (ikke i git)
└── output/                 De færdige videoer (ikke i git)
```

---

## Sådan kører man den

```bash
# Lav en video for verdens-kanalen
python run.py --channel world

# Lav en video for sports-kanalen
python run.py --channel sports

# Bare se ét frame for at tjekke layoutet
python run.py --channel world --preview-frame
```

Hvilket emne der bliver lavet, og hvordan det skal se ud, styres fra
`config.json`.

---

## Status

- **WorldStatsRaces** (verdensdata) — kører, har lavet ~10 videoer.
- **SportStatsRaces** (fodbold) — bruger samme videomotor, men kører i dag
  uden voiceover. Stemme og musik er det næste der skal kobles på.
