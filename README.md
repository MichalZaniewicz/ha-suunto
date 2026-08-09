# Suunto → Home Assistant (`suunto_app`)

A custom HACS integration that pulls your **Suunto** data into Home Assistant from
the Suunto app (Sports Tracker) - signing in with just your email and password,
no Docker and no partner keys.

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=MichalZaniewicz&repository=ha-suunto&category=integration)

![Suunto example dashboard](https://raw.githubusercontent.com/MichalZaniewicz/ha-suunto/main/docs/dashboard.jpg)

*Example dashboard - live sensors plus backfilled long-term statistics (heart
rate, training load, sleep).*

> [!TIP]
> ⭐ **Enjoying this integration?** Every star is real motivation for me to keep
> developing it :)

<!-- The badge lives OUTSIDE the alert on purpose: Home Assistant rewrites a
GitHub alert into <ha-alert> and drops every child whose textContent is empty,
which silently removes any <img> placed inside it. -->

[![Star this repo](https://img.shields.io/github/stars/MichalZaniewicz/ha-suunto?style=for-the-badge&logo=github&label=STAR%20THIS%20REPO&labelColor=555555&color=ffc107)](https://github.com/MichalZaniewicz/ha-suunto)

```
Suunto watch ──▶ Suunto app / Sports Tracker ──▶ Home Assistant
```

> ⚠️ **Unofficial integration** - not affiliated with or endorsed by Suunto. It
> signs in with your own Suunto account and may stop working after a Suunto app
> update. Use your own account, at your own risk. Login pipeline ported from
> [`tajchert/suuntool`](https://github.com/tajchert/suuntool).

## Documentation

Full docs are in the **[project wiki](https://github.com/MichalZaniewicz/ha-suunto/wiki)**:
installation, every sensor, dashboard examples, derived metrics, long-term
statistics and troubleshooting.

## Custom Lovelace cards

Want a dashboard without wiring 74 sensors into generic entity/gauge cards by hand?
**[Suunto Cards](https://github.com/MichalZaniewicz/ha-suunto-cards)** is a companion
HACS repo with 7 purpose-built cards - last workout, HR zones, sleep & readiness,
recovery, training load, week & lifetime stats, and a live "today" snapshot. Each
card auto-detects your Suunto device (zero YAML for the common case), themes with
your Home Assistant theme automatically, and follows your HA language (English,
Polish, German, Portuguese, French, Spanish, Italian, Dutch).

![Suunto Cards preview](https://raw.githubusercontent.com/MichalZaniewicz/ha-suunto-cards/master/docs/screenshots/cards-overview-dark.png)

## Installation & configuration

1. Install via HACS (Custom repositories → this repo as an **Integration**) and restart HA.
2. **Settings → Devices & Services → Add Integration → "Suunto App (unofficial)"**
   → enter the **email and password** of your Suunto app account. (Account 2FA may
   block login.)
3. Options ("Configure" button): two refresh cadences -
   - **Live data interval** (default 15 min): current heart rate, daily steps/energy.
   - **History interval** (default 60 min): sleep, recovery, workouts, training
     load, baselines and other derived metrics - and the hourly long-term
     statistics (see [below](#long-term-statistics-intraday-curves--backfill)).

   Splitting the cadences keeps live values fresh without re-fetching ~90 days of
   history every few minutes.

### Credential storage

The password is used **only once** (at setup), exchanged for a **session token**,
and is **not stored**. Only the email and the revocable session token are written
to HA's `.storage`. If the session ever expires, HA shows "reauthentication
required" and asks for the password once (reauth) - the password is still not
kept between times.

### "New login" emails

Suunto sends a new-login notification on **every** `/login2` call. The integration
**caches the session token** and reuses it across restarts - it only logs in again
on first setup or when the server invalidates the session. During normal operation
(data fetching) it **does not log in and does not generate emails**.

### Diagnostics

Settings → Devices & Services → the Suunto entry's **⋮ menu → Download diagnostics**
gives a redacted JSON dump of the integration's current state (useful when
reporting a bug). Email, session token and GPS start coordinates are stripped;
everything else - including the raw 24/7 sleep export used to build the sleep and
nap sensors - is included as-is.

## Entities (74 sensors + 2 binary sensors + a workouts calendar under one "Suunto" device)

The device card itself shows your actual **watch model** (e.g. "Suunto 9 Peak
Pro"), read from your most recent workout - not just "Suunto App (unofficial)".

- **Sleep:** duration, stages (deep/light/REM), average/min heart rate, quality,
  SpO₂, HRV, sleep start, wake-up time, and **nap duration** (tracked separately
  from night sleep so a nap never inflates it; state holds the most recent day
  that had a nap, with `nap_count` and `date` attributes since naps are
  irregular and the value can be several days old).
- **Recovery:** recovery balance, stress state.
- **Daily activity:** steps, active energy (kcal), current heart rate.
- **Last workout:** type, start, **start location** (latitude/longitude - plots on
  a Map card), distance, duration, recovery time, average/max heart rate,
  average speed (km/h) and pace (min/km), cadence, **TSS**, **time in 5
  heart-rate zones**, **Peak Training Effect** (Suunto's own 1-5 rating of the
  session), **peak EPOC**, your own **feeling** rating (1-5, when you set it on the
  watch), the workout **type** as Suunto classifies it (commute, strength, long
  aerobic base ...; the raw list is in the sensor's `tags` attribute), and
  **recovered-at** (when the recovery countdown ends).
  Each heart-rate zone sensor also carries its **bpm range** in the
  `lower_limit_bpm` / `upper_limit_bpm` attributes, so "38 min in zone 3" reads as
  an actual effort. Zone 1 is everything below zone 2, so it has an upper bound
  only; the top of zone 5 is your max heart rate.
- **Last workout - weather:** on-site **temperature** (°C) as the sensor state,
  with **humidity**, **wind speed** (km/h), **wind direction** and a decoded
  **condition** (e.g. "Scattered clouds") in its attributes. Outdoor workouts
  only - unknown on an indoor session, since there's no weather to record.
- **Last workout - achievements:** state is how many route achievements (e.g.
  "Fastest time on this route") the workout earned - 0 on most workouts, since
  Suunto only awards these on a route you've ridden/run before. The full raw
  list and this workout's `route_ranking` (if Suunto tracked one) are in the
  attributes.
- **Last workout - climbing:** ascent and descent (m), time spent climbing and
  descending, and the **altitude range** (min/max). Indoor sessions have no
  barometer data, so the altitude sensors stay unknown there.
- **Lifetime stats:** total distance (km), total time (h), total energy, number of
  workouts, active days, plus a **per-sport breakdown** (distance/time/count/energy
  for each activity type, in the sensor's attributes).
- **Fitness:** **VO2max**, estimated VO2max and **fitness age**, as measured by the
  watch. Suunto derives these from **runs and walks only**, so they hold their last
  reading between such workouts - each sensor's `measured_at` attribute shows when
  (and from which activity) it was taken.
- **Derived - training load:** Fitness (CTL), Fatigue (ATL), Form (TSB) from TSS
  history, plus the acute:chronic workload ratio (ACWR; safe zone ~0.8-1.3).
- **Derived - recovery:** HRV baseline + status (low/balanced/high), resting heart
  rate + baseline, and **Readiness** (0-100, a heuristic blending sleep, HRV,
  resting HR and recovery balance).
- **Derived - per workout:** % of max HR, calories per km, ascent rate, stride length.
- **Weekly volume:** workout distance and time over the last 7 days.
- **Counts:** workouts in the last 7 / 30 days.
- **Workouts calendar & recent list:** a `calendar` entity with every past workout
  as a browsable event, plus a *Recent workouts* sensor whose attribute holds the
  last 15 (date, type, distance, duration, HR, TSS) - see below.
- **Binary sensors:** *Recovering* (on while Suunto's recovery countdown from the
  last workout is still running) and *Workout today*. Both flip on their own
  clock, so they change the moment the countdown ends or the day rolls over,
  without waiting for the next poll.

### Automations: the new-workout event

When a workout first reaches the integration (i.e. after your watch has synced to
the Suunto app), it fires a `suunto_app_new_workout` event on the Home Assistant
bus, so you don't have to watch a sensor for changes:

```yaml
automation:
  - alias: Notify me about a new workout
    triggers:
      - trigger: event
        event_type: suunto_app_new_workout
    actions:
      - action: notify.persistent_notification
        data:
          message: >
            {{ trigger.event.data.activity }}:
            {{ (trigger.event.data.distance_meters | float(0) / 1000) | round(1) }} km
            in {{ trigger.event.data.duration_minutes }} min,
            TSS {{ trigger.event.data.tss }}, PTE {{ trigger.event.data.pte }}
```

The event carries `key`, `activity`, `activity_id`, `start_time`,
`duration_minutes`, `distance_meters`, `avg_hr_bpm`, `max_hr_bpm`, `tss`, `pte`,
`recovery_time_hours` and `tags`. The first poll after a Home Assistant restart
only takes stock of what already exists, and a workout that shows up more than a
week after it happened is recorded silently - your history is never replayed as a
burst of events.

> Derived metrics are computed locally in HA from history fetched via the API
> (sleep ~60 days, workouts ~90 days, paginated). CTL/ATL are seeded with the mean
> daily load to avoid an early-window underestimate. **Readiness** and its weights
> are a heuristic, not an official Suunto metric. All the math (CTL/ATL/TSB, ACWR,
> baseline, readiness) is covered by deterministic tests in `metrics.py`.

## Long-term statistics (intraday curves + backfill)

![Suunto long-term statistics charts](https://raw.githubusercontent.com/MichalZaniewicz/ha-suunto/main/docs/charts.jpg)

*Backfilled statistics: intraday heart rate (24/7 + workout peaks) and the
Fitness / Fatigue / Form (CTL / ATL / TSB) trend.*

Beyond the 74 live sensors, the integration imports **hourly long-term
statistics** for the fast-changing and daily metrics. They are backfilled over a
rolling window, so if your watch syncs to the app late (e.g. hours later), the
missed hours are filled in **retroactively** - something a normal sensor can't do,
since it only records the latest value at poll time.

These are external statistics (`suunto_app:...`), **not entities** - view them in a
**Statistics Graph** card (or ApexCharts); they don't add to the sensor count.

- **Hourly:** heart rate (mean/min/max - the 10-min 24/7 stream **plus** the dense
  ~25 s heart-rate samples from workouts, so workout peaks show up), steps, energy,
  recovery balance, stress.
- **Daily:** sleep duration, HRV, resting heart rate, quality, SpO₂; Readiness;
  and the Fitness / Fatigue / Form (CTL/ATL/TSB) trend.

The backfill window is ~5 days - a sync delayed beyond that won't fill the part
older than the window. The hourly **heart-rate** statistic is the way to see a
gap-free daily HR curve (with workout peaks); the live `current_hr` sensor only
steps to the newest synced value and can't be filled backwards.

## Workouts calendar & recent activities

![Suunto workouts calendar and recent activities list](https://raw.githubusercontent.com/MichalZaniewicz/ha-suunto/main/docs/workouts.jpg)

Every past workout is exposed as an event on a **`calendar`** entity - browse your
whole training history in a Calendar card, each event showing the activity,
distance and key stats (duration, HR, TSS). A companion **Recent workouts** sensor
keeps the last 15 sessions in its attributes for a compact list/table card. Both
reuse the workout history already fetched - no extra requests.

## Workout start on a map

The **Last workout location** sensor carries the start **latitude/longitude** of
your most recent workout as attributes, so it can be plotted directly on a Map card:

```yaml
type: map
entities:
  - sensor.suunto_last_workout_location   # your entity id (named after the account)
```

Indoor workouts with no GPS track show as *unknown* (no marker). The same
`start_lat` / `start_lon` are also present on every entry of the **Recent workouts**
sensor's attributes, if you'd like to plot more than just the latest one (e.g. with
a template sensor or a custom card).

## Lifetime totals per sport

The **Lifetime by activity** sensor's state is the number of activity types; the
per-sport totals ride in its `activities` attribute (each with `activity`,
`workouts`, `distance_km`, `time_hours`, `energy_kcal`). Render them with a Markdown
card:

```yaml
type: markdown
content: |
  | Sport | Workouts | Distance | Time |
  | --- | --: | --: | --: |
  {% for a in state_attr('sensor.suunto_lifetime_by_activity', 'activities') -%}
  | {{ a.activity }} | {{ a.workouts }} | {{ a.distance_km }} km | {{ a.time_hours }} h |
  {% endfor %}
```

## Troubleshooting

- **"Login was rejected"** - wrong email/password, or account 2FA.
- **"Reauthentication required"** - the session expired; enter the password again.
- **Light/REM sleep sensors are `unknown`** - your watch does not report them.
- **Daily energy dropped by ~4x after updating to 1.0.14** - that is the fix, not
  a regression. The value was previously read as calories when the API sends
  joules. It is **active** energy (above resting), so it is meant to be well
  below your total daily burn. Existing history is not rewritten, so expect a
  step in the graph; you can clear the old long-term statistics in
  **Developer Tools > Statistics** if the jump bothers you.
- **Altitude sensors are `unknown` after an indoor workout** - intended. Without
  GPS or a barometer reading the watch reports no altitude, and showing 0 m would
  claim you trained at sea level.
- **Stride length is `unknown`** - it is only computed for foot-based activities,
  so it stays empty after a ride.

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## Disclaimer

An unofficial, experimental hobby project - run it at your own risk.

- **No ties to Suunto.** Not affiliated with, endorsed by, or supported by Suunto
  Oy, Amer Sports, or Sports-Tracker. All trademarks stay with their owners.
- **Built on shifting ground.** It talks to a private, undocumented endpoint that
  can change or stop working at any moment - a single app update may break it.
- **Possibly against Suunto's terms.** Check them yourself. Hammering the service
  could get your account limited or closed; that's on you, not the author.
- **Your account only.** Use it strictly for your own data - never to collect or
  aggregate anyone else's.
- **No warranty, no liability.** Provided "as is", with no guarantees and no
  responsibility for anything that follows from using it.
- Not legal advice. If any of this gives you second thoughts, just use the
  official Suunto app.
