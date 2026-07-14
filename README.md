# Suunto → Home Assistant (`suunto_app`)

A custom HACS integration that pulls your **Suunto** data into Home Assistant from
the Suunto app (Sports Tracker) — signing in with just your email and password,
no Docker and no partner keys.

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=MichalZaniewicz&repository=ha-suunto&category=integration)

![Suunto example dashboard](https://raw.githubusercontent.com/MichalZaniewicz/ha-suunto/main/docs/dashboard.jpg)

*Example dashboard — live sensors plus backfilled long-term statistics (heart
rate, training load, sleep).*

```
Suunto watch ──▶ Suunto app / Sports Tracker ──▶ Home Assistant
```

> ⚠️ **Unofficial integration** — not affiliated with or endorsed by Suunto. It
> signs in with your own Suunto account and may stop working after a Suunto app
> update. Use your own account, at your own risk. Login pipeline ported from
> [`tajchert/suuntool`](https://github.com/tajchert/suuntool).

## Installation & configuration

1. Install via HACS (Custom repositories → this repo as an **Integration**) and restart HA.
2. **Settings → Devices & Services → Add Integration → "Suunto App (unofficial)"**
   → enter the **email and password** of your Suunto app account. (Account 2FA may
   block login.)
3. Options ("Configure" button): two refresh cadences —
   - **Live data interval** (default 15 min): current heart rate, daily steps/energy.
   - **History interval** (default 60 min): sleep, recovery, workouts, training
     load, baselines and other derived metrics — and the hourly long-term
     statistics (see [below](#long-term-statistics-intraday-curves--backfill)).

   Splitting the cadences keeps live values fresh without re-fetching ~90 days of
   history every few minutes.

### Credential storage

The password is used **only once** (at setup), exchanged for a **session token**,
and is **not stored**. Only the email and the revocable session token are written
to HA's `.storage`. If the session ever expires, HA shows "reauthentication
required" and asks for the password once (reauth) — the password is still not
kept between times.

### "New login" emails

Suunto sends a new-login notification on **every** `/login2` call. The integration
**caches the session token** and reuses it across restarts — it only logs in again
on first setup or when the server invalidates the session. During normal operation
(data fetching) it **does not log in and does not generate emails**.

## Entities (57 sensors + a workouts calendar under one "Suunto" device)

- **Sleep:** duration, stages (deep/light/REM), average/min heart rate, quality,
  SpO₂, HRV, sleep start, wake-up time.
- **Recovery:** recovery balance, stress state.
- **Daily activity:** steps, energy (kcal), current heart rate.
- **Last workout:** type, start, **start location** (latitude/longitude — plots on
  a Map card), distance, duration, ascent, recovery time, average/max heart rate,
  average speed (km/h) and pace (min/km), cadence, **TSS**, and **time in 5
  heart-rate zones**.
- **Lifetime stats:** total distance (km), total time (h), total energy, number of
  workouts, active days.
- **Derived — training load:** Fitness (CTL), Fatigue (ATL), Form (TSB) from TSS
  history, plus the acute:chronic workload ratio (ACWR; safe zone ~0.8–1.3).
- **Derived — recovery:** HRV baseline + status (low/balanced/high), resting heart
  rate + baseline, and **Readiness** (0–100, a heuristic blending sleep, HRV,
  resting HR and recovery balance).
- **Derived — per workout:** % of max HR, calories per km, ascent rate, stride length.
- **Weekly volume:** workout distance and time over the last 7 days.
- **Counts:** workouts in the last 7 / 30 days.
- **Workouts calendar & recent list:** a `calendar` entity with every past workout
  as a browsable event, plus a *Recent workouts* sensor whose attribute holds the
  last 15 (date, type, distance, duration, HR, TSS) — see below.

> Derived metrics are computed locally in HA from history fetched via the API
> (sleep ~60 days, workouts ~90 days, paginated). CTL/ATL are seeded with the mean
> daily load to avoid an early-window underestimate. **Readiness** and its weights
> are a heuristic, not an official Suunto metric. All the math (CTL/ATL/TSB, ACWR,
> baseline, readiness) is covered by deterministic tests in `metrics.py`.

## Long-term statistics (intraday curves + backfill)

![Suunto long-term statistics charts](https://raw.githubusercontent.com/MichalZaniewicz/ha-suunto/main/docs/charts.jpg)

*Backfilled statistics: intraday heart rate (24/7 + workout peaks) and the
Fitness / Fatigue / Form (CTL / ATL / TSB) trend.*

Beyond the 55 live sensors, the integration imports **hourly long-term
statistics** for the fast-changing and daily metrics. They are backfilled over a
rolling window, so if your watch syncs to the app late (e.g. hours later), the
missed hours are filled in **retroactively** — something a normal sensor can't do,
since it only records the latest value at poll time.

These are external statistics (`suunto_app:…`), **not entities** — view them in a
**Statistics Graph** card (or ApexCharts); they don't add to the sensor count.

- **Hourly:** heart rate (mean/min/max — the 10-min 24/7 stream **plus** the dense
  ~25 s heart-rate samples from workouts, so workout peaks show up), steps, energy,
  recovery balance, stress.
- **Daily:** sleep duration, HRV, resting heart rate, quality, SpO₂; Readiness;
  and the Fitness / Fatigue / Form (CTL/ATL/TSB) trend.

The backfill window is ~5 days — a sync delayed beyond that won't fill the part
older than the window. The hourly **heart-rate** statistic is the way to see a
gap-free daily HR curve (with workout peaks); the live `current_hr` sensor only
steps to the newest synced value and can't be filled backwards.

## Workouts calendar & recent activities

![Suunto workouts calendar and recent activities list](https://raw.githubusercontent.com/MichalZaniewicz/ha-suunto/main/docs/workouts.jpg)

Every past workout is exposed as an event on a **`calendar`** entity — browse your
whole training history in a Calendar card, each event showing the activity,
distance and key stats (duration, HR, TSS). A companion **Recent workouts** sensor
keeps the last 15 sessions in its attributes for a compact list/table card. Both
reuse the workout history already fetched — no extra requests.

## Troubleshooting

- **"Login was rejected"** – wrong email/password, or account 2FA.
- **"Reauthentication required"** – the session expired; enter the password again.
- **Light/REM sleep sensors are `unknown`** – your watch does not report them.

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## Disclaimer

An unofficial, experimental hobby project — run it at your own risk.

- **No ties to Suunto.** Not affiliated with, endorsed by, or supported by Suunto
  Oy, Amer Sports, or Sports-Tracker. All trademarks stay with their owners.
- **Built on shifting ground.** It talks to a private, undocumented endpoint that
  can change or stop working at any moment — a single app update may break it.
- **Possibly against Suunto's terms.** Check them yourself. Hammering the service
  could get your account limited or closed; that's on you, not the author.
- **Your account only.** Use it strictly for your own data — never to collect or
  aggregate anyone else's.
- **No warranty, no liability.** Provided "as is", with no guarantees and no
  responsibility for anything that follows from using it.
- Not legal advice. If any of this gives you second thoughts, just use the
  official Suunto app.
