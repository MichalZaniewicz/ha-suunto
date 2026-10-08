# Suunto → Home Assistant (`suunto_app`)

![Suunto for Home Assistant](https://raw.githubusercontent.com/MichalZaniewicz/ha-suunto/main/docs/hero-banner.svg)

A custom HACS integration that pulls your **Suunto** data into Home Assistant from
the Suunto app (Sports Tracker) - signing in with just your email and password,
no Docker and no partner keys.

> [!TIP]
> ⭐ **Enjoying this integration?** Every star is real motivation for me to keep
> developing it :)
>
> ☕ Want to say thanks another way? You can [buy me a coffee](https://buymeacoffee.com/zanula).

<!-- The badge lives OUTSIDE the alert on purpose: Home Assistant rewrites a
GitHub alert into <ha-alert> and drops every child whose textContent is empty,
which silently removes any <img> placed inside it. -->

[![Star this repo](https://img.shields.io/github/stars/MichalZaniewicz/ha-suunto?style=for-the-badge&logo=github&label=STAR%20THIS%20REPO&labelColor=555555&color=ffc107)](https://github.com/MichalZaniewicz/ha-suunto) [![Buy me a coffee](https://img.shields.io/badge/BUY%20ME%20A%20COFFEE-FFDD00?style=for-the-badge&logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/zanula)

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=MichalZaniewicz&repository=ha-suunto&category=integration)

```
Suunto watch ──▶ Suunto app / Sports Tracker ──▶ Home Assistant
```

> ⚠️ **Unofficial integration** - not affiliated with or endorsed by Suunto. It
> signs in with your own Suunto account and may stop working after a Suunto app
> update. Use your own account, at your own risk. Login pipeline ported from
> [`tajchert/suuntool`](https://github.com/tajchert/suuntool).

## Documentation

![Suunto for Home Assistant - trailer](https://raw.githubusercontent.com/MichalZaniewicz/ha-suunto/main/docs/trailer.webp)

Full docs are in the **[project wiki](https://github.com/MichalZaniewicz/ha-suunto/wiki)**:
installation, every sensor, dashboard examples, derived metrics, long-term
statistics and troubleshooting.

## Custom Lovelace cards

Want a dashboard without wiring 104 sensors into generic entity/gauge cards by hand?
**[Suunto Cards](https://github.com/MichalZaniewicz/ha-suunto-cards)** is a companion
HACS repo with 66 purpose-built cards - last workout, HR zones, sleep & readiness,
recovery, training load, a live 24/7 heart rate curve, an activity heatmap
calendar, workout-to-workout comparisons, fun lifetime-distance equivalents, a
computed training personality, a FIFA-style player card, 20 unlockable
achievements, a game-style level/XP bar, an RPG training class, a next-milestone
countdown, a lifetime story card, a 24h sleep clock, a sleep-regularity chart, a
single-night sleep deep-dive with sleep efficiency, commute savings, gear
service tracking, a form forecast, a one-sentence daily brief, the daily AI insight with one tab per
section, and more. Each card auto-detects your Suunto
device (zero YAML for the common case), themes with your Home Assistant theme
automatically, and follows your HA language (English, Polish, German,
Portuguese, French, Spanish, Italian, Dutch).

![Suunto Cards preview](https://raw.githubusercontent.com/MichalZaniewicz/ha-suunto-cards/master/docs/screenshots/cards-overview-dark.png)

## Installation & configuration

1. Install via HACS (Custom repositories → this repo as an **Integration**) and restart HA.
2. **Settings → Devices & Services → Add Integration → "Suunto App (unofficial)"**
   → enter the **email and password** of your Suunto app account. (Account 2FA may
   block login.)
3. Options ("Configure" button) open a small menu: **intervals and fuel
   figures**, the optional **AI daily insight** (see
   [AI daily insight](#ai-daily-insight-optional)), and **gear** (add / mark as
   serviced / remove, see [Gear tracking](#gear-tracking-and-service-reminders)). Two refresh cadences -
   - **Live data interval** (default 15 min): current heart rate, daily steps/energy.
   - **History interval** (default 60 min): sleep, recovery, workouts, training
     load, baselines and other derived metrics - and the hourly long-term
     statistics (see [below](#long-term-statistics-intraday-curves--backfill)).

   Splitting the cadences keeps live values fresh without re-fetching ~90 days of
   history every few minutes. The same screen holds your car's **fuel
   consumption** and the **fuel price** (default 7 l/100 km and 6.5 per litre),
   used only for the commute savings below.

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

## Entities (104 sensors + 3 binary sensors + a workouts calendar under one "Suunto" device)

Every entity name follows your Home Assistant language automatically - English, Polish, German,
Portuguese, French, Spanish, Italian and Dutch are built in. Anything else falls back to English.
(Display names only; `entity_id`s never change with your language.)

The device card itself shows your actual **watch model** (e.g. "Suunto 9 Peak
Pro"), read from your most recent workout - not just "Suunto App (unofficial)".

- **Sleep:** duration, stages (deep/light/REM), average/min heart rate, quality,
  SpO₂, HRV, sleep start, wake-up time, and **nap duration** (tracked separately
  from night sleep so a nap never inflates it; state holds the most recent day
  that had a nap, with `nap_count` and `date` attributes since naps are
  irregular and the value can be several days old).
- **Recovery:** recovery balance, stress state.
- **Daily activity:** steps and active energy (kcal), each with a `goal`
  attribute holding the target you set in the Suunto app, **total energy** (active plus
  your basal metabolic rate accrued so far today - the same "calories" figure the
  Suunto app shows), **BMR** (kcal/day, from the weight, height, age and sex in
  your Suunto profile, Mifflin-St Jeor formula, the one the app uses; the inputs
  ride in its attributes), current heart rate (the newest
  24/7 reading that has one, so it doesn't drop to unknown during a workout; its
  `measured_at` attribute shows when it was taken).
- **Last workout:** type, start, **days since** (a rest-day counter - 0 means
  you trained today, handy as an automation trigger), **start location**
  (latitude/longitude - plots on a Map card, plus a downsampled `route` attribute
  with the full GPS track and per-point speed for a custom, pace-colored route
  card), distance, duration, recovery time, average/max heart rate, average
  speed (km/h) and pace (min/km),
  **cadence** (rpm - Suunto reports it as cycles/min for every sport; on foot-based
  activities the sensor also carries a `cadence_spm` attribute, the steps/min
  equivalent, so the state itself never changes and your history isn't rewritten),
  **TSS** (an alternative MET-based figure rides alongside it in the `tss_met`
  attribute, when Suunto computed one), **time in 6 heart-rate zones (0-5)**, **Peak Training
  Effect** (Suunto's own 1-5 rating of the session), **peak EPOC**, your own
  **feeling** rating (1-5, when you set it on the watch), the workout **type**
  as Suunto classifies it (commute, strength, long aerobic base ...; the raw
  list is in the sensor's `tags` attribute, alongside `is_manually_added` -
  whether you typed the workout in rather than synced it from the watch), and
  **recovered-at** (when the recovery countdown ends). A workout recorded
  **without heart rate** is flagged with `has_hr: false` on the TSS and
  recovery sensors (its TSS is then Suunto's MET-based estimate); if Suunto
  capped its recovery time at exactly 5 days, the watch's own summary value is
  used instead and the original rides in `reported_recovery_time_hours`.
  Each heart-rate zone sensor also carries its **bpm range** in the
  `lower_limit_bpm` / `upper_limit_bpm` attributes, so "38 min in zone 3" reads as
  an actual effort. Zone 0 is everything below zone 1, zone 1 is everything below
  zone 2 - most watches don't report a numeric split between zones 0 and 1
  specifically, so zone 0 usually has no bpm range of its own even though its
  duration is always there; the top of zone 5 is your max heart rate.
- **Last workout - laps:** state is how many laps the workout has; each lap in the
  `laps` attribute carries its own duration, distance and pace. 0 on a workout with
  no manual/auto laps, which is most of them.
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
- **This year:** the same five totals again (distance, time, energy, workouts,
  active days) scoped to the current calendar year instead of your whole
  history - a running "year in review". Resets on January 1st; the workouts
  sensor's attributes also carry the year's single most-common activity
  (e.g. "Cycling, 62% of this year's workouts").
- **This month:** the same five totals once more, scoped to the current
  calendar month - resets on the 1st. Same shape as the yearly version above,
  including its own most-common-activity attribute.
- **Training records:** state is your longest-ever workout streak (consecutive
  days); attributes carry four more all-time personal records - fastest pace,
  biggest single-workout climb, longest single workout, farthest single
  workout, and highest single-session TSS - each with the workout it happened
  in. Seeded once via a deep history scan (same technique the VO2max sensor
  uses) and only ever improved from there, so these are true lifetime bests,
  not bounded to the normal fetch window.
- **Training records - this month:** the same five personal records, scoped to
  the current calendar month instead of your whole history - quietly resets on
  the 1st. No deep scan needed (a month always fits inside the normal fetch
  window), so it's always exactly in sync with this month's workouts.
- **Training records - this year:** the same five personal records again,
  scoped to the current calendar year - a running "training year in review".
  Resets on January 1st; like the all-time sensor above (and unlike the
  monthly one) it needs its own deep history scan to pick up January's
  workouts once they've aged out of the normal fetch window.
- **Current streak:** how many days in a row you've trained, right now -
  resets to 0 the moment a day is skipped. A different question from
  *Training records*' all-time longest streak above: that one only ever goes
  up, this one tracks whether you're on one today.
- **Best efforts:** state is how many standard distances (1K, 5K, 10K, half
  marathon, marathon) have a recorded personal best so far; each one's time
  and the workout it happened in ride in attributes. Foot-based activities
  only, computed from the same detailed GPS/pace data already fetched for
  the route/lap sensors - the fastest continuous stretch covering at least
  that distance within a single workout. **Tracked from when you install
  this version onward, not retroactively** - a genuine best from before you
  updated won't be found unless you happen to beat it again.
- **Fitness:** **VO2max**, estimated VO2max and **fitness age**, as measured by the
  watch. Suunto derives these from **runs and walks only**, so they hold their last
  reading between such workouts - each sensor's `measured_at` attribute shows when
  (and from which activity) it was taken. The same three numbers are also
  imported as a **long-term statistics trend** (see below), so you can chart
  them over time instead of only seeing today's held value.
- **Derived - training load:** Fitness (CTL), Fatigue (ATL), Form (TSB) from TSS
  history, plus the acute:chronic workload ratio (ACWR; safe zone ~0.8-1.3), and
  a **training suggestion** (rest/easy/moderate/hard) for today, derived from
  those same two numbers - a spiking ACWR (>1.5) always suggests rest,
  regardless of how fresh your form looks.
- **Form forecast:** state is your form (TSB) **tomorrow if you rest today**.
  Attributes project a full rest from today: `peak_tsb`, `peak_date` and
  `days_to_peak` (when you would be freshest), `maintenance_tss_week` (the
  weekly load that holds your fitness where it is), and a 28-day `series` of
  CTL/ATL/TSB for a chart. A what-if, not a prediction of what you will do.
- **Daily brief:** one sentence for today in your Home Assistant language,
  built from the sensors above - e.g. "Slept 8.0 h, HRV above your norm,
  readiness 76, form +27: a good day for a hard session." Put it on a
  dashboard or have a speaker read it. It only restates the other sensors, so
  it never disagrees with them.
- **AI insight (optional):** a daily review written by an AI model of your
  choice, with advice and a status for the day, plus a button to run it on
  demand - see [AI daily insight](#ai-daily-insight-optional). On top of the
  104 sensors, and only there once you turn it on.
- **Sync now button:** fetches everything from Suunto right away instead of
  waiting for the next poll (every 15 min for activity, every 60 min for
  sleep, recovery and workouts), with the stored session, so no new login
  email. It cannot reach your watch: sync the watch with the Suunto app first,
  then press it. If the full night comes in with it, the woke-up event and
  the AI insight follow as usual.
- **Patterns in your own history** (from the 60 nights and 90 days of
  workouts already fetched, no extra requests):
  - **Sleep regularity:** the Sleep Regularity Index (-100..100) over the last
    four weeks: the chance of being asleep or awake at the same minute on two
    days in a row, so 100 is an identical schedule every day. Attributes:
    `avg_bedtime`, `avg_wake_time`, their spread in minutes (`bedtime_sd_min`,
    `wake_time_sd_min`), and how many `nights` / `pairs` it is based on.
    Needs at least 5 pairs of consecutive nights.
  - **Social jetlag:** how many minutes later the middle of your sleep sits on
    Friday and Saturday nights than on work nights (`free_midpoint`,
    `work_midpoint` in attributes). Negative means earlier on weekends.
  - **Aerobic decoupling:** how much your heart rate drifted against your
    speed between the first and second half of the newest workout that is
    long enough (40+ min after a 5-min warm-up, with GPS). Under ~5 % is the
    classic sign of a solid aerobic base. Attributes carry both halves' speed
    and heart rate, and `history` lists recent workouts for a trend. Speed,
    not power, so terrain and wind make one value rough; watch the trend.
    Workouts are checked as their data is downloaded, so after an update or a
    restart the history refills from your newest workouts onward.
  - **Personal insights:** what goes with better or worse nights for you,
    e.g. "After a workout ending after 20:00, your HRV is 21% lower (39 ms vs
    50 ms)". It compares nights after late workouts, training days, your
    hardest days, early bedtimes and weekend nights against the rest, for HRV,
    resting HR and sleep length, and only keeps clear differences (at least 4
    nights on each side). The state is the strongest one in your Home
    Assistant language; `insights` holds up to 5 (one per kind of night, its
    strongest metric), each with the numbers,
    `favorable` and the sentence. These are correlations in your own data,
    not proof of cause. The AI insight gets them as context too.
- **Commutes:** distance commuted **this month** and **this year**, counting
  whatever Suunto itself tagged as a commute. Attributes carry `rides`,
  `days`, `avg_duration_min`, and what the car left at home would have cost:
  `fuel_saved_l`, `money_saved` (your currency) and `co2_saved_kg` (tailpipe),
  plus the `fuel_l_per_100km` / `fuel_price_per_litre` they were computed with.
- **Gear:** one distance sensor per piece of gear you define (chain, tyres,
  shoes...), with `interval_km`, `remaining_km` and `service_due` attributes -
  see [Gear tracking](#gear-tracking-and-service-reminders). These are on top
  of the 104 sensors.
- **Derived - recovery:** HRV baseline + status (low/balanced/high), resting heart
  rate + baseline, and **Readiness** (0-100, a heuristic blending sleep, HRV,
  resting HR and recovery balance). If last night's sleep hasn't arrived by
  noon (watch not worn, wrong watch clock, not synced), readiness is scored on
  recovery balance alone instead of on an older night; its `sleep_night` /
  `sleep_stale` attributes (and `night` / `stale` on the sleep-duration sensor)
  show which night is being used.
- **Derived - per workout:** % of max HR, calories per km, ascent rate, stride length.
- **Weekly volume:** workout distance, time and **steps** over the last 7 days
  (steps are read back from the hourly step statistics below, since they come
  from the 24/7 stream rather than the workout list).
- **Counts:** workouts in the last 7 / 30 days.
- **Workouts calendar & recent list:** a `calendar` entity with every past workout
  as a browsable event, plus a *Recent workouts* sensor whose attribute holds the
  last 60 (date, type, distance, duration, HR, TSS) - see below.
- **Binary sensors:** *Recovering* (on while Suunto's recovery countdown from the
  last workout is still running), *Workout today*, and **Unusual recovery** (on
  when your resting heart rate is elevated *and* your HRV is suppressed at the
  same time, both vs. your own sleep-night baseline - a commonly used early
  signal of illness or overreaching, not a diagnosis; stays `unknown` until
  there is enough sleep history to have a real baseline). The first two flip on
  their own clock, so they change the moment the countdown ends or the day
  rolls over, without waiting for the next poll; *Unusual recovery* only
  changes when new sleep data arrives.

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

### Automations: the woke-up event

When a new sleep night first reaches the integration (after your morning watch
sync), it fires `suunto_app_woke_up` once. The event carries `night`,
`wake_time`, `sleep_hours`, `sleep_quality_pct`, `hrv_ms`, `hrv_status`,
`resting_hr_bpm` and `readiness`. Like the workout event it fires when the data
arrives, not at the moment you wake up; the first poll after a restart only
takes stock, and an out-of-date night is never announced. The watch also syncs
during the night, so a night only counts once its last part ends at 4:00 or
later; a fragment that arrives at 2 a.m. waits for the rest of the night.

### Gear tracking and service reminders

Under the integration's **Configure -> Add gear to track**, give a piece of gear
a name, pick the sport it wears with (e.g. Cycling for a chain), how many km it
already has, and a service interval. It becomes its own distance sensor that
counts every kilometre of that sport from then on - no history scan, it uses
the per-sport lifetime totals already fetched. **Mark gear as serviced** resets
it to 0 km. Pair it with the *Gear Service Reminder* blueprint below to get a
notification when the interval is reached.

### AI daily insight (optional)

Once a day an AI model reads your sleep, recovery and training data and writes
a review: a headline, an overall call for the day, four short sections (sleep,
health and recovery, training, daily activity) each with its own status, a few
concrete pieces of advice, and a warning only when something needs attention.
Where the daily brief restates the other sensors, this one connects them and
looks at the trend.

**How to turn it on** (Home Assistant 2025.8 or newer):

1. Add an AI provider as a normal integration if you have none yet:
   **Settings -> Devices & Services -> Add Integration** -> Google Gemini (has a
   free tier), OpenAI, Anthropic, Ollama (runs locally), or any other one that
   offers an *AI Task* entity.
2. Open this integration's **Configure -> AI daily insight** and pick that AI
   Task entity. Optionally add notes for the model ("Preparing for a marathon
   on 12 April") and the fallback hour. Save.
3. Optional: put the **AI Insight** card from
   [Suunto Cards](https://github.com/MichalZaniewicz/ha-suunto-cards) on a
   dashboard, and import the **AI Insight Report** blueprint (below) to get the
   review as a notification.

**No API key goes into this integration**: it uses Home Assistant's own
[AI Task](https://www.home-assistant.io/integrations/ai_task/), so the key stays
with the provider integration you set up in step 1. To turn the feature off
again, clear the entity in the same Configure screen.

**How it works:**

- It runs once a day, right after your morning watch sync brings in last
  night's sleep. If no new night has arrived by the fallback hour (10:00 by
  default), it runs anyway and once more when the night shows up. The result
  is stored, so a restart never pays for it twice.
- The **Generate AI insight** button runs it on demand. The **Automatic AI
  insight** switch pauses the automatic runs, so nothing is spent while it is
  off (the button still works, and the last result stays).
- The review is written in your Home Assistant language. The activity section
  judges yesterday's complete day, since in the morning today has barely
  started.

#### Details

It sends a compact summary of numbers the integration has already computed
(last night's sleep, 14 nights of HRV and resting HR, baselines, readiness,
CTL/ATL/TSB/ACWR, the form forecast, the last 14 days of workouts, yesterday's
and today's steps and active calories, your Suunto app goals) - roughly 1-3k tokens, so a cent or less per day
on cloud models, and within Gemini's free tier. Nothing extra is fetched from
Suunto. The answer is in the Home Assistant language.

The *AI insight* sensor's state is the headline. Attributes: `status`
(`good` / `ok` / `caution` / `rest`, the overall call for today), `sections`,
`advice` (a list), `warning`, `for_date`, `generated_at`, `sleep_night` /
`sleep_stale` (which night it was based on), `ai_task_entity`, `generating`,
`paused` and `error` (the last failure, if any). The long text is kept out of the
recorder.

`sections` splits the review by topic, always in this order, each with its own
`status` (`good` / `ok` / `caution`) and `text` (two paragraphs, separated by a
blank line); a section with no data is left out:

| Key | Covers |
| --- | --- |
| `sleep` | last night's duration, deep/REM and quality, consistency over the last nights, the sleep goal |
| `recovery` | HRV and resting HR against your baselines, readiness, recovery balance, stress |
| `training` | the last 14 days of workouts, CTL/ATL/TSB/ACWR, weekly volume, the form forecast |
| `activity` | yesterday's complete steps and active calories against your goals (today so far only as a partial figure), the streak |

```yaml
{{ state_attr('sensor.suunto_michala_ai_insight', 'sections').sleep.text }}
```

Every successful run also fires a `suunto_app_ai_insight` event carrying
`headline`, `status`, `sections`, `advice`, `warning`, `manual` (true when it
came from the button) and `labels` (section and status names in your Home
Assistant language). The *AI Insight Report* blueprint below turns it into a
notification.

> [!WARNING]
> Your health data goes to whichever AI provider you pick. Use a local model
> (Ollama) if it should stay at home. The insight is written by a language
> model: it can be wrong, and it is not medical advice.

### Automation blueprints

Eight ready-to-import blueprints under
[`blueprints/automation/suunto_app/`](blueprints/automation/suunto_app/) wrap the
patterns above so you don't have to write the YAML yourself - each just asks for
an *action* (e.g. "Send a notification") and the entities/thresholds it needs:

| Blueprint | What it does | Import |
| --- | --- | --- |
| [New Workout Notification](blueprints/automation/suunto_app/new_workout_notification.yaml) | Runs your action with a one-line workout summary whenever `suunto_app_new_workout` fires. | [![Open your Home Assistant instance and show the blueprint import dialog with the new-workout-notification blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FMichalZaniewicz%2Fha-suunto%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsuunto_app%2Fnew_workout_notification.yaml) |
| [Low Readiness Alert](blueprints/automation/suunto_app/low_readiness_alert.yaml) | Runs your action once when the Readiness sensor drops below a threshold you set. | [![Open your Home Assistant instance and show the blueprint import dialog with the low-readiness-alert blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FMichalZaniewicz%2Fha-suunto%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsuunto_app%2Flow_readiness_alert.yaml) |
| [Unusual Recovery Alert](blueprints/automation/suunto_app/unusual_recovery_alert.yaml) | Runs your action the moment the Unusual recovery sensor turns on. | [![Open your Home Assistant instance and show the blueprint import dialog with the unusual-recovery-alert blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FMichalZaniewicz%2Fha-suunto%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsuunto_app%2Funusual_recovery_alert.yaml) |
| [Weekly Training Digest](blueprints/automation/suunto_app/weekly_digest.yaml) | Runs your action with a weekly summary (workouts, distance, time, form) on the day(s)/time you pick. | [![Open your Home Assistant instance and show the blueprint import dialog with the weekly-digest blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FMichalZaniewicz%2Fha-suunto%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsuunto_app%2Fweekly_digest.yaml) |
| [Good Morning Routine](blueprints/automation/suunto_app/good_morning.yaml) | Runs one action after a good night and another after a rough one (readiness threshold you set) when `suunto_app_woke_up` fires. | [![Open your Home Assistant instance and show the blueprint import dialog with the good-morning blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FMichalZaniewicz%2Fha-suunto%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsuunto_app%2Fgood_morning.yaml) |
| [After a Long Workout](blueprints/automation/suunto_app/long_workout_finished.yaml) | Runs your action when a new workout at least as long as your threshold syncs in. | [![Open your Home Assistant instance and show the blueprint import dialog with the long-workout-finished blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FMichalZaniewicz%2Fha-suunto%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsuunto_app%2Flong_workout_finished.yaml) |
| [Gear Service Reminder](blueprints/automation/suunto_app/gear_service_reminder.yaml) | Runs your action once when a tracked piece of gear reaches its service interval. | [![Open your Home Assistant instance and show the blueprint import dialog with the gear-service-reminder blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FMichalZaniewicz%2Fha-suunto%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsuunto_app%2Fgear_service_reminder.yaml) |
| [AI Insight Report](blueprints/automation/suunto_app/ai_insight_report.yaml) | Sends the daily AI insight when it is generated: short (headline, section statuses, warning, advice) or full, for the sections and days you pick. | [![Open your Home Assistant instance and show the blueprint import dialog with the ai-insight-report blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FMichalZaniewicz%2Fha-suunto%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fsuunto_app%2Fai_insight_report.yaml) |

Or import manually: Settings -> Automations & Scenes -> Blueprints -> Import
Blueprint, and paste a blueprint's GitHub URL.

> Derived metrics are computed locally in HA from history fetched via the API
> (sleep ~60 days, workouts ~90 days, paginated). CTL/ATL are seeded with the mean
> daily load to avoid an early-window underestimate. **Readiness**, **training
> suggestion**, **unusual recovery**, the **form forecast** and the **daily
> brief** are heuristics, not official Suunto metrics. All the math (CTL/ATL/TSB, ACWR, baseline, readiness, training
> suggestion, unusual recovery) is covered by deterministic tests in
> `metrics.py`.

## Long-term statistics (intraday curves + backfill)

![Suunto long-term statistics charts](https://raw.githubusercontent.com/MichalZaniewicz/ha-suunto/main/docs/charts.jpg)

*Backfilled statistics: intraday heart rate (24/7 + workout peaks) and the
Fitness / Fatigue / Form (CTL / ATL / TSB) trend.*

Beyond the 104 live sensors, the integration imports **hourly long-term
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
  the Fitness / Fatigue / Form (CTL/ATL/TSB) trend; peak Training Effect /
  peak EPOC (the day's hardest session, when there was more than one); and
  VO2max / estimated VO2max / fitness age - sparse, since Suunto only computes
  these from runs and walks, but every reading you get is charted as a point
  in the trend rather than only living in the live sensors' held state.

The backfill window is ~5 days - a sync delayed beyond that won't fill the part
older than the window. The hourly **heart-rate** statistic is the way to see a
gap-free daily HR curve (with workout peaks); the live `current_hr` sensor only
steps to the newest synced value and can't be filled backwards.

## Workouts calendar & recent activities

![Suunto workouts calendar and recent activities list](https://raw.githubusercontent.com/MichalZaniewicz/ha-suunto/main/docs/workouts.jpg)

Every past workout is exposed as an event on a **`calendar`** entity - browse your
whole training history in a Calendar card, each event showing the activity,
distance and key stats (duration, HR, TSS). A companion **Recent workouts** sensor
keeps the last 60 sessions in its attributes for a compact list/table card. Both
reuse the workout history already fetched - no extra requests.

Each entry in **Recent workouts** also carries `cadence_spm` and
`stride_length_m` - the same running-dynamics figures behind the Cadence/Stride
sensors below, present only for foot-based activities (running, walking,
trekking), `null` otherwise - so a custom card can chart cadence or stride
trend across your recent runs.

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

The same sensor also carries a `route` attribute: the last workout's full GPS
track as a downsampled `[[lat, lon, speed_kmh], ...]` list (up to 300 points),
each vertex carrying its own speed so a custom card can color the route by pace
without a second data source. It's deliberately excluded from Home Assistant's
recorder (only the live state matters for this), so it won't bloat your history
database. `route` is absent on indoor workouts, same as `latitude`/`longitude`.

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
