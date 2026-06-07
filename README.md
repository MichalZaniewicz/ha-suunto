# Suunto → Home Assistant (`suunto_app`)

A custom HACS integration that pulls your **Suunto** data into Home Assistant from
the Suunto app (Sports Tracker) — signing in with just your email and password,
no Docker and no partner keys.

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
     load, baselines and other derived metrics.

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

## Entities (54 sensors under one "Suunto" device)

- **Sleep:** duration, stages (deep/light/REM), average/min heart rate, quality,
  SpO₂, HRV, sleep start.
- **Recovery:** recovery balance, stress state.
- **Daily activity:** steps, energy (kcal), current heart rate.
- **Last workout:** type, start, distance, duration, ascent, recovery time,
  average/max heart rate, average speed (km/h) and pace (min/km), cadence, **TSS**,
  and **time in 5 heart-rate zones**.
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

> Derived metrics are computed locally in HA from history fetched via the API
> (sleep ~60 days, workouts ~90 days, paginated). CTL/ATL are seeded with the mean
> daily load to avoid an early-window underestimate. **Readiness** and its weights
> are a heuristic, not an official Suunto metric. All the math (CTL/ATL/TSB, ACWR,
> baseline, readiness) is covered by deterministic tests in `metrics.py`.

## Verification status

- **Login, data fetching and field mapping verified against a live account** —
  sleep (`duration/deepSleepDuration/hrAvg/hrMin/maxSpo2/quality/avgHrv`), recovery
  (`balance/stressState`), activity (`stepCount/energyConsumption/hr`), workouts
  (zones, TSS, speed/pace, cadence, HR) and lifetime stats.
- `energyConsumption` is in calories (÷1000 → kcal); `timeInZone` is in centiseconds.
- `lightSleepDuration`/`remSleepDuration` may be absent depending on the watch
  model (then light/REM sleep is `unknown`).
- **Not exercised inside a live Home Assistant** (config flow / coordinator at
  runtime) — checked statically and against real data via the API.

## Troubleshooting

- **"Login was rejected"** – wrong email/password, or account 2FA.
- **"Reauthentication required"** – the session expired; enter the password again.
- **Light/REM sleep sensors are `unknown`** – your watch does not report them.
