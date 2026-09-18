# Verifying global weather models at Chinese stations

Ten operational global models — eight physics-based and two machine-learned —
nine Chinese airport stations and eight Chinese photovoltaic sites, fourteen
months, three variables, verified at a **fixed forecast lead**, which is the
part most comparisons skip. Temperature and wind are scored against station
observations; solar irradiation, where no station instrument exists, against a
satellite retrieval.

The question is not which model wins a global average. It is which one is
closest **here**, on the variable you actually care about, and how much of its
error is a constant anyone could remove.

## The finding

**There is no best model. There is a best model per variable, and the ranking
inverts between them.**

![Rank reversal across three variables](reports/figures/rank_reversal_ai_window.png)

Six models, three variables, one shared six-month window. DWD ICON is first on
temperature, **last on wind**, and first again on irradiation. CMA GRAPES is
fifth on temperature, **first on wind**, and last on irradiation. NOAA GFS runs
the same pattern in reverse. Only ECCC GEM holds the same place on all three,
and that place is third.

| Model | Temperature | 10 m wind | Solar irradiation |
|---|---|---|---|
| DWD ICON | **1** | 6 | **1** |
| ECMWF AIFS (AI) | 4 | 5 | 2 |
| ECCC GEM | 3 | 3 | 3 |
| ECMWF IFS | 2 | 4 | 4 |
| NOAA GFS | 6 | **2** | 5 |
| CMA GRAPES | 5 | **1** | 6 |

Over the full fourteen-month archive, where only temperature and wind exist, the
same reversal appears at the four control stations in London, Frankfurt, New York
and Tokyo, so it is a property of the models rather than of China.

![Rank reversal over the full archive](reports/figures/rank_reversal.png)

Anyone choosing a weather data provider on one headline accuracy figure is
choosing wrong for every other use they have. For a wind-power operator in
China, the model that the international comparisons rank near the bottom is the
one that was closest to the anemometer. For a solar operator, the model that won
the wind comparison is the worst of the six.

## Where the machine-learned models land

ECMWF AIFS is the operational machine-learned forecast, and placing it against
the physics models at Chinese stations is the question this repository was built
for. It enters the archive on 2025-02-21, so it is scored on its own window —
March to August 2025, 183 days — with the physics models restricted to exactly
the same days.

**At one day ahead AIFS does not win the station variables.** Fourth of seven
on daily maximum temperature, sixth of seven on 10 m wind, and its deficit
against ECMWF IFS is significant on both: +0.22 °C and +0.11 m/s of mean
absolute error, bootstrap intervals excluding zero.

**On solar irradiation it is already level, and it beats ECMWF's own physics
model.** Second of six at day 1, 1,000 Wh/m² against DWD ICON's 999 — a paired
difference of +11 Wh/m² with an interval of −26 to +47 that spans zero, which is
a tie and not a loss. Against ECMWF IFS, the model from the same institution, it
is **228 Wh/m² better** in mean absolute error, interval −260 to −196. By day 5
it is first outright, and by a margin no physics model comes near.

![AIFS on solar irradiation](reports/figures/ai_vs_physics_shortwave_radiation.png)

| Model | Day 1 | Day 5 | Growth |
|---|---|---|---|
| **ECMWF AIFS (AI)** | 1,000 | **1,296** | +29.5% |
| DWD ICON | **999** | 1,459 | +46.1% |
| ECMWF IFS | 1,254 | 1,518 | +21.1% |
| ECCC GEM | 1,115 | 1,642 | +47.2% |
| NOAA GFS | 1,270 | 1,674 | +31.8% |
| CMA GRAPES | 1,402 | 1,736 | +23.9% |

RMSE of daily solar irradiation, Wh/m², eight photovoltaic sites, six-model
common sample. Mean observed irradiation is 5,457 Wh/m², so day-1 RMSE runs from
18.3% of the daily total for ICON and AIFS to 25.7% for CMA GRAPES.

This is the variable a photovoltaic forecast is built on, and it is the one where
the machine-learned model is already competitive at the lead a dispatch centre
submits on. Note also where ECMWF IFS lands: fourth of six, 23.0% against ICON's
18.3%. The model with the best global reputation is not the one to drive a solar
forecast with here.

**Across all three variables its error grows the slowest or close to it.**

![AIFS against six physics models](reports/figures/ai_vs_physics.png)

| Model | Day 1 | Day 5 | Growth |
|---|---|---|---|
| **ECMWF AIFS (AI)** | 2.46 | 2.87 | **+16.9%** |
| NOAA GFS | 2.61 | 3.15 | +20.6% |
| ECMWF IFS | 2.07 | 2.68 | +29.0% |
| CMA GRAPES | 2.46 | 3.23 | +31.4% |
| JMA GSM | 2.64 | 3.47 | +31.6% |
| ECCC GEM | 2.36 | 3.15 | +33.4% |
| DWD ICON | **1.87** | 2.72 | +45.1% |

RMSE of daily maximum temperature, °C, Chinese stations, seven-model common
sample.

The gap between AIFS and ECMWF IFS narrows from 0.39 °C at day 1 to 0.19 °C at
day 5; against ICON, which wins day 1 outright, it narrows from 0.59 to 0.15.
The same shape appears on wind and at the four control stations, so it belongs
to the model and not to the region.

That is the known signature of a machine-learned forecast — smoother fields,
less sharpness at short range, and a shallower decay because there is no
imperfect dynamical integration accumulating error. Two consequences worth
stating plainly:

- **For day-ahead station variables these models are not the answer here yet.**
  At the lead a dispatch centre actually submits on, every well-ranked physics
  model was closer on temperature and on 10 m wind.
- **For day-ahead irradiation the answer has already changed.** AIFS is level
  with the best physics model and ahead of four of the other five, on the
  variable that drives photovoltaic output.
- **For the medium range the choice is not arguable, it is made.** AIFS is first
  on irradiation by day 5 and closing on the others elsewhere. A verification
  quoted at a single lead and a single variable — which is most of them — hides
  all of this.

GraphCast is in the archive but covers 37 to 59 per cent of days depending on
the variable, so it is reported separately rather than dropped or averaged over
the days it happened to run.

## The scorecards

**Daily maximum 2 m temperature**, day-1 lead, nine Chinese stations, 3,733
pairs on the days all six models ran:

| Model | RMSE | Bias | MAE | RMSE after debiasing | Misses ≥ 3 °C |
|---|---|---|---|---|---|
| DWD ICON | **1.70** | −0.80 | 1.36 | 1.50 | 7.3% |
| ECMWF IFS | 2.02 | −1.11 | 1.65 | 1.69 | 13.9% |
| ECCC GEM | 2.16 | −0.97 | 1.70 | 1.93 | 16.9% |
| NOAA GFS | 2.32 | −0.69 | 1.83 | 2.21 | 19.7% |
| CMA GRAPES | 2.49 | −1.45 | 2.02 | 2.02 | 23.7% |
| JMA GSM | 2.56 | −1.58 | 2.04 | 2.01 | 23.6% |

**Daily mean 10 m wind speed**, same stations, same days, metres per second:

| Model | RMSE | Bias | MAE | RMSE after debiasing |
|---|---|---|---|---|
| CMA GRAPES | **0.89** | −0.16 | 0.65 | 0.88 |
| ECCC GEM | 1.07 | −0.36 | 0.83 | 1.01 |
| ECMWF IFS | 1.09 | −0.76 | 0.88 | **0.78** |
| NOAA GFS | 1.11 | −0.32 | 0.83 | 1.06 |
| JMA GSM | 1.23 | −0.67 | 1.00 | 1.03 |
| DWD ICON | 1.54 | −1.27 | 1.29 | 0.86 |

Note the last column. ECMWF and ICON have the *smallest* wind error once their
offsets are removed, and the *largest* offsets. Their wind problem is
calibration; CMA GRAPES's is not, because it barely has one.

![Error growth with lead time](reports/figures/lead_growth_wind_speed_10m.png)

**Daily solar irradiation**, eight photovoltaic sites, day-1 lead, 7,740 pairs
over the 173 days all six models ran, Wh/m² against a satellite retrieval:

| Model | RMSE | % of daily total | Bias | MAE | RMSE after debiasing |
|---|---|---|---|---|---|
| DWD ICON | **999** | 18.3% | −231 | **788** | **972** |
| ECMWF AIFS (AI) | 1,000 | 18.3% | −174 | 799 | 985 |
| ECCC GEM | 1,115 | 20.4% | +92 | 834 | 1,111 |
| ECMWF IFS | 1,254 | 23.0% | −204 | 1,027 | 1,237 |
| NOAA GFS | 1,270 | 23.3% | +115 | 940 | 1,264 |
| CMA GRAPES | 1,402 | 25.7% | +51 | 1,120 | 1,401 |

Unlike temperature, irradiation bias is small and signed both ways, and
debiasing changes almost nothing: the last column is within 3% of the first for
every model. There is no constant offset to remove here. The error is
day-to-day cloud, which is the hard part and the reason a solar forecast is
harder than a temperature forecast.

## What else it found

**Every model runs cold on the daily maximum, and it is not a China effect.**
Biases run from −0.69 to −1.58 °C. The obvious hypothesis is something Chinese —
urban heat, siting, the monsoon — and it is wrong: the four control stations in
London, Frankfurt, New York and Tokyo show a mean bias of −0.99 °C against
China's −1.10 °C. Whatever causes it, these models under-predict the afternoon
peak at airports generally. That is worth knowing before anyone builds a
correction that assumes a local cause.

**Every model also runs slow on wind**, by 0.16 to 1.27 m/s. Under-forecasting
wind speed matters more than the number suggests: turbine power goes as roughly
the cube of wind speed near the middle of the power curve, so ICON's 1.27 m/s
deficit on a 3.5 m/s mean is not a 36% error in the input, it is most of the
output.

**A small bias is not the same as a good model.** Squared bias accounts for 38%
of JMA's mean squared error, 34% of CMA GRAPES's and 30% of ECMWF's, but only 9%
of GFS's. Remove each model's constant offset and the middle of the table
reshuffles: GFS drops from fourth to sixth, JMA climbs from sixth to fourth.
GFS looked respectable because its bias was small, not because its day-to-day
errors were.

![Bias versus skill](reports/figures/bias_vs_skill.png)

**CMA GRAPES is fifth of six, and a third of that is a fixable offset.** It
carries the second-largest cold bias in the set. On the wider eight-model
comparison at leads 1 to 3 it moves up two places once debiased. Anyone using it
operationally in China should fit a per-station offset before anything else; on
this sample that single number removes about a third of its mean squared error.

![Bias by station](reports/figures/station_bias.png)

Station biases are not uniform. GFS is 3.0 °C cold at Hong Kong and 1.4 °C
**warm** at Shenzhen, two stations 30 km apart, which is a coastal
representativeness problem rather than a model-physics one.

## Why fixed lead is the whole study

An earlier version of this dataset was assembled from Open-Meteo's historical
forecast archive, which returns the best forecast available for each hour. That
is the right choice for trading and the wrong one for verification: the "best
available" forecast is whatever the most recent run said, at whatever lead that
happened to be, and averaging over it produces a score that describes no product
anyone can buy.

This version uses the previous-runs archive, where
`temperature_2m_previous_day3` means exactly "what this model said three days
before", per model. Every number here is at a stated lead.

Three more choices that decide whether a scorecard means anything:

- **Common sample.** Models drop out of the archive. Météo-France ARPEGE is only
  held to day 3; UKMO covers 60% of days. A mean over whatever days a model
  happened to run rewards it for the days it skipped, so every comparison is
  restricted to days on which every model in that comparison produced a forecast.
  Hence two sets: six models at leads 1–5, all eight at leads 1–3.
- **Paired tests.** Two models verified on the same 400 days saw the same
  weather and are not independent samples. Differences are tested as per-day
  differences in absolute error with a bootstrap over days, and a model is only
  called better when the interval excludes zero.
- **Bias reported separately from error.** A model that is two degrees cold every
  day and one that is two degrees out at random both have an RMSE of two. Only
  one of them is fixable with a constant.

## What it does not show

- **Airports, not cities.** METAR is the only free, genuinely observed hourly
  temperature record, and it comes from airports, which sit on flat open ground
  outside town on purpose. A model verified at ZBAA has not been verified over
  Beijing's third ring road.
- **Nine stations.** Enough to rank models, not enough to map regional skill.
- **10 m is not hub height, and it cannot be fixed here.** A turbine hub sits at
  80 to 120 m, where the wind is stronger, smoother and differently biased.
  Extrapolating these 10 m results up a shear profile is a further assumption,
  not a result. Verifying 100 m wind directly would need a hub-height
  observation, and no free one exists at these sites — a reanalysis is not an
  observation, and scoring forecasts against one would mostly measure how close
  each model is to ECMWF's analysis. **100 m wind is therefore reported as
  unverified rather than verified against a substitute.** Nothing here says
  anything about precipitation.
- **The irradiance truth is a satellite retrieval, not a pyranometer.** It is
  what the solar industry assesses resource with, and it is the only hourly
  irradiance record available at these sites, but it carries its own error —
  several per cent on daily totals, more under broken cloud. Part of every
  irradiance score in this study is retrieval error rather than forecast error.
  The comparison between models is unaffected, because all six are scored
  against the same retrieval; the absolute numbers are upper bounds.
- **The photovoltaic coordinates were recovered, not given.** The eight sites
  come from an anonymised operator dataset with no locations, and their
  positions were fitted from the generation series itself. One of the eight
  lands just outside the national border in eastern Myanmar, which it cannot
  actually be, so its satellite pixel is the wrong pixel by some tens of
  kilometres. It is kept and named rather than quietly dropped. A second site,
  at 78.7°E, sits between the Himawari and Meteosat-IODC disks and has satellite
  coverage on only 79 of the 173 days.
- **Hourly sampling.** Both the forecast and the observation are reduced to the
  maximum of 24 hourly values, so both miss the instantaneous peak. The
  comparison is fair; the absolute maxima are slightly low.
- **One AI model properly, one partially.** AIFS is scored over its full window;
  GraphCast is patchy. Pangu and FuXi are in no archive this study can reach at
  a fixed lead without downloading global fields, which is the next step and a
  much heavier one.
- **Deterministic runs only.** AIFS also publishes an ensemble, and setting one
  deterministic member against physics-model ensembles would be a different and
  more flattering question than the one asked here.

## Running it

```bash
conda create -n aiwp python=3.11 -y && conda activate aiwp
pip install pandas pyarrow numpy scipy matplotlib pytest
pip install -e .

make verify figures   # every table and figure, from the pairs committed in data/
make test             # 37 tests
make data             # optional: rebuild the pairs from the archives (slow, quota-bound)
```

`make data` runs `aiwp.build_dataset` once per variable and window — temperature
and wind over the full archive, then temperature, wind and irradiance over the
AI window — and prints a coverage audit for each.

## Data

| What | Source | Licence |
|---|---|---|
| Forecasts at fixed lead, 8 models, days 1–5 | [Open-Meteo previous-runs archive](https://open-meteo.com/en/docs/previous-runs-api) | CC BY 4.0, free for non-commercial use |
| Station observations, hourly METAR | [Iowa State Mesonet ASOS archive](https://mesonet.agron.iastate.edu/request/download.phtml) | public, no account |
| Satellite-retrieved irradiance, hourly | [Open-Meteo satellite radiation archive](https://open-meteo.com/en/docs/satellite-radiation-api) (Himawari, Meteosat IODC) | CC BY 4.0, free for non-commercial use |

198,333 temperature pairs and 180,518 wind pairs over 427 days
(2024-07-01 to 2025-08-31), plus 102,612 and 92,771 over the 184-day AI window
(2025-03-01 to 2025-08-31), and 45,287 irradiance pairs at eight photovoltaic
sites over the same window. Thirteen stations and eight sites.

The derived forecast–observation pairs are committed under `data/` (about 5 MB),
so every table and figure here reproduces without fetching anything. The raw
archives are not redistributed; `build_dataset` rebuilds the pairs from source.
The pairs carry the licences of what they were derived from, listed above.

Units are checked rather than assumed. Open-Meteo returns wind in km/h unless
asked otherwise and METAR reports it in knots; comparing either against the
other as if it were m/s inflates a forecast by 3.6 or 1.9 times while producing
a scorecard that still looks like a scorecard. The fetcher asks for m/s
explicitly and then asserts that m/s is what came back.

The three variables are in three different units, and the columns holding them
carried a `_c` suffix from the days when temperature was the only one. The
suffix is gone and every printed table names its unit, because a reader who has
just seen a table in degrees will carry degrees into the next one. Irradiation is
an hourly mean summed over the day, so it is energy: **Wh/m², not W/m².**

Physics models: ECMWF IFS 0.25°, NOAA GFS, DWD ICON, JMA GSM, ECCC GEM,
Météo-France ARPEGE, UKMO, and **CMA GRAPES** — the Chinese operational global
model, which does not appear in the published international comparisons.

Machine-learned models: **ECMWF AIFS Single** and **GraphCast** (GFS-initialised).
Both come through the same archive as the physics models, so no global fields
are downloaded and the lead control is identical.

## Layout

```
src/aiwp/
  stations.py          the nine Chinese stations and four controls with ICAO
                       codes, and the eight photovoltaic sites
  fetch.py             fixed-lead forecasts, METAR observations, daily reduction,
                       and a unit guard on what the API returns
  verify.py            scores, common sample, paired bootstrap
  build_dataset.py     fetch everything, print the coverage audit
  run_verification.py  scorecards, significance tests, cross-variable ranking
  make_figures.py      eleven figures from six templates
tests/                 37 tests, expectations hand-computed
reports/               scorecards, results.json, figures
```

## Related repositories

- [pv-wind-power-forecast](https://github.com/Zhaohh0706/pv-wind-power-forecast) — PV and wind forecasting, priced against Chinese grid-code assessment
- [cn-weather-cube](https://github.com/Zhaohh0706/cn-weather-cube) — point weather with units attached and sources named
- [green-ai-ledger](https://github.com/Zhaohh0706/green-ai-ledger) — compute energy and carbon, with the grid factor pinned rather than guessed
