# Changelog

Notable changes per release. Releases are published on GitHub (HACS reads them);
beta pre-releases are tagged `X.Y.ZbN`.

## 1.0.19b1
- **New `training_suggestion` sensor.** A rest/easy/moderate/hard read on
  today's effort, derived from your existing Form (TSB) and ACWR - a spiking
  ACWR (>1.5, the same elevated-injury-risk threshold the ACWR sensor already
  documents) always suggests rest, regardless of how fresh your form looks.
  No extra API calls - reuses the training-load numbers already computed.
- **New `unusual_recovery` binary sensor.** On when your resting heart rate is
  elevated *and* your HRV is suppressed at the same time, both versus your own
  sleep-night baseline - either signal alone is noisy, but both moving the
  wrong way together is a commonly used early signal of illness or
  overreaching (not a diagnosis). Stays `unknown` until there is enough sleep
  history for a real baseline, rather than reading as a false "fine".
- **Automation blueprints.** Three ready-to-import blueprints under
  `blueprints/automation/suunto_app/`: a new-workout push notification, a
  low-readiness alert, and a weekly training digest. See the README for the
  one-click import badges.

## 1.0.18
- **Time in HR zone 0.** The five zone sensors (1-5) now have a sixth
  sibling, `last_zone0` - time spent below zone 1, too easy to register in
  any real zone. Same `lower_limit_bpm`/`upper_limit_bpm` attribute pattern
  as the others, though most watches don't report a numeric split between
  zones 0 and 1 specifically, so zone 0 usually has no bpm range of its own
  even though its duration is always there.
- **New `last_workout_laps` sensor.** State is how many laps your last
  workout has; each lap in the `laps` attribute carries its own duration,
  distance and pace. Reuses the same `workouts/{key}/data` fetch already
  made for the dense heart-rate statistics - no extra requests.
- **Peak Training Effect and peak EPOC as daily long-term statistics**
  (`suunto_app:pte`, `suunto_app:epoc`), alongside the existing CTL/ATL/TSB
  trend - so a session's training impact gets the same backfilled history
  view the load metrics already have, instead of only ever showing the last
  workout's value. On a day with more than one workout, the day's MAX is
  used (the hardest session of the day).

## 1.0.17
- **7 more languages.** Every sensor/binary sensor/calendar name and the
  config/options flow text now has Polish, German, Portuguese, French,
  Spanish, Italian and Dutch translations, alongside the existing English -
  Home Assistant picks the right one automatically based on your HA
  language. Display names only; `entity_id`s are unchanged.
- **New companion repo: [Suunto Cards](https://github.com/MichalZaniewicz/ha-suunto-cards).**
  7 purpose-built Lovelace cards (last workout, HR zones, sleep & readiness,
  recovery, training load, week & lifetime stats, today) instead of wiring
  this integration's 74 sensors into generic entity/gauge cards by hand.
  Zero-config for one Suunto account, themes with your HA theme, and comes
  with the same 8 languages as above. Separate HACS repo (category
  Dashboard) - install it alongside this integration.

  ![Suunto Cards preview](https://raw.githubusercontent.com/MichalZaniewicz/ha-suunto-cards/master/docs/screenshots/cards-overview-dark.png)

## 1.0.16
- **Watch model on the device card.** The Suunto device now shows your actual
  watch (e.g. "Suunto 9 Peak Pro") instead of the generic "Suunto App
  (unofficial)", read from your most recent workout's recorded gear. Updates
  itself if it wasn't known yet (a brand-new account) or you switch watches.
- **New `last_workout_weather` sensor.** On-site temperature (°C) as the
  state; humidity, wind speed/direction and a decoded condition (e.g.
  "Scattered clouds") in the attributes. Outdoor workouts only.
- **New `last_workout_achievements` sensor.** State is the number of route
  achievements ("Fastest time on this route", ...) the workout earned (0 on
  most); the raw list and the workout's route ranking are in the attributes.
- **New `nap_duration` sensor.** Night sleep (`sleep_duration` and the other
  `sleep_*` sensors) deliberately excludes naps so a daytime nap never inflates
  a night's numbers - that filter stays. Naps are now tracked on their own
  instead of simply being dropped: the new sensor shows the most recent day's
  total nap time (minutes), with `nap_count` and `date` attributes, since naps
  are irregular and the value can be several days old.
- **Diagnostics support.** Settings → Devices & Services → the Suunto entry's
  ⋮ menu → *Download diagnostics* now works, giving a redacted JSON dump of the
  integration's state (email, session token and GPS start coordinates
  stripped) - including the raw 24/7 sleep export, to make bug reports about
  sleep/nap bucketing reproducible without needing the reporter's account.

## 1.0.15
- **Heart-rate zone thresholds.** Each *time in HR zone* sensor now carries that
  zone's bpm range in its `lower_limit_bpm` / `upper_limit_bpm` attributes, read
  from the workout's `IntensityExtension`. Until now the integration reported how
  long you spent in zone 3 without ever saying what zone 3 was. Suunto sends no
  lower limit for zone 1 (it is simply everything below zone 2), so that zone
  shows an upper bound alone rather than an invented floor, and the top of zone 5
  comes from your max heart rate.
- **Three new sensors:** `last_epoc` (peak EPOC, the oxygen debt the session
  built up - Peak Training Effect is derived from it), `last_feeling` (your own
  1-5 rating, present only when you set it on the watch) and `last_workout_tags`
  (how Suunto itself classifies the session - commute, strength, long aerobic
  base and so on; the raw list is in the `tags` attribute).
- **Two binary sensors:** *Recovering* (on while the recovery countdown from the
  last workout is still running) and *Workout today*. Both flip on their own
  clock, so they change the moment the countdown ends or the day rolls over
  instead of waiting for the next poll.
- **`suunto_app_new_workout` event** on the Home Assistant bus, so automations
  can react to a finished workout without watching a sensor for changes. It
  carries the activity, start time, duration, distance, average and max heart
  rate, TSS, PTE, recovery time and tags. The first poll after a restart only
  takes stock of what already exists, and a workout that surfaces late (more than
  7 days after it happened) is recorded silently - your history is never replayed
  as a burst of events, and neither is a flaky fetch mistaken for an empty
  account.
- Faster: an unchanged workout is normalized once instead of on every hourly
  cycle (the whole 90-day window used to be reprocessed each time), and the
  workouts calendar builds its events once per update rather than on every card
  query.
  As with the previous release, none of the new data costs an extra API call -
  every field was already in the workout response.

## 1.0.14
- Fixed: the long-term statistics import now declares `unit_class`, which
  **Home Assistant 2026.11 will require**. Until then HA derives one and logs a
  deprecation warning; without this the whole statistics import (heart rate,
  steps, energy, sleep, training load) would stop working on that release. The
  value is derived exactly the way the recorder derives it today, so no existing
  statistic changes class and history stays continuous.
- **Peak Training Effect** sensor (`last_pte`) - Suunto's own 1..5 rating of how
  hard the last session hit you, read from the workout's `SummaryExtension`.
- **Descent, climb/descend times and altitude range** for the last workout:
  `last_descent`, `last_ascent_time`, `last_descent_time`, `last_min_altitude`
  and `last_max_altitude`. Indoor sessions carry no barometer data, so the
  altitude pair stays unknown there rather than reporting sea level; a flat
  outdoor workout correctly reads 0 m of descent. Note that `minAltitude` /
  `maxAltitude` arrive in **decimetres** (unlike ascent and descent, which are
  metres) and are converted - verified against the per-point altitude track,
  where the ratio is exactly 10 from a 120 m city commute to a 2656 m alpine
  hike.
  None of the above costs an extra API call - the fields were already in the
  workout response.
- Fixed: **daily energy was about 4.19x too high**. `energyConsumption` from the
  24/7 stream is in joules, not calories, and was being divided by 1000 instead
  of 4186.8. Corrected in the live sensor and in the hourly statistics import.
  Values drop accordingly after this update; existing history is not rewritten.
- Fixed: **daily steps and energy no longer inflate the long-term statistics**.
  Both are `TOTAL_INCREASING`, so Home Assistant read any dip in the
  eventually-consistent Suunto export as a meter reset and added the next full
  reading to the running total. The coordinator now clamps a dip to the highest
  value already seen for that local date, and starts a fresh cycle on a new date.

## 1.0.13
- **VO2max, estimated VO2max and fitness age** sensors, read from the watch's own
  `FitnessExtension` (no extra API calls - the data was already in the workout
  response). Suunto computes these from **runs and walks only**, so each sensor
  holds its last reading and carries `measured_at` / `measured_from` attributes
  showing when and from which activity it was taken. If the normal 90-day window
  has no such workout, a one-off deeper history scan seeds them.
- Fixed: `strings.json` was missing the `wake_time` and `workouts_recent` entries
  that `translations/en.json` already had.

## 1.0.12
- **Workout start location** - a new `last_workout_location` sensor exposing the
  last workout's start latitude/longitude (decoded from the GPS track) as
  attributes, so it can be plotted directly on a Map card. Indoor workouts with
  no GPS show as unknown. Start coordinates (`start_lat`/`start_lon`) are also on
  every entry of the Recent workouts sensor attributes.
- **Recovered-at** sensor (`recovery_until`) - a timestamp for when the last
  workout's recovery countdown finishes (workout end + recovery time).
- **Lifetime by activity** sensor - lifetime totals split per sport
  (distance/time/count/energy for each activity type) in the sensor's attributes.

## 1.0.11
- **Workouts calendar** - a `calendar` entity exposing every past workout as a
  browsable event (activity, distance, duration / HR / TSS).
- **Recent workouts** sensor - the last 15 sessions in its attributes for a
  list/table card.
- Activity-type names mapped: Walking, Soccer, Volleyball, Trekking, Kayaking
  (previously shown as "Activity N").
- README documents the calendar / recent list with a screenshot.

## 1.0.10
- Docs only: example dashboard + long-term statistics screenshots in the README;
  removed the developer-facing "Verification status" section.

## 1.0.9
- Sleep **wake-up time** sensor (derived as the end of the last sleep fragment;
  the API has no explicit wake field).
- Statistics import now declares `mean_type` (fixes the Home Assistant 2026.11
  deprecation), with a fallback to `has_mean` on cores older than 2024.12.

## 1.0.8
- Hourly statistics backfill extended to **sleep** (duration / HRV / resting HR /
  quality / SpO₂), **Readiness** and the **CTL/ATL/TSB** trend.
- Backfill window widened to 5 days; workout heart-rate samples cached;
  cumulative-sum base read made gap-tolerant.

## 1.0.7
- **Hourly long-term statistics** for fast-changing metrics (heart rate, steps,
  energy, recovery), with dense workout heart-rate folded into the HR series so an
  intraday curve backfills retroactively after a late sync.
- Fixed the 7-day sensors' "notch" caused by the eventually-consistent workouts
  list (per-key cache with a grace window).

## 1.0.6
- Stride length only for foot-based activities.

## 1.0.5
- Workout HR zones; recovery shows `0` instead of `unknown`.

## 1.0.4
- Per-sensor display precision (no more long floating-point artifacts).

## 1.0.3
- Inline brand icons so the integration-page icon shows (HA 2026.3+).

## 1.0.0 - 1.0.2
- Initial releases: email/password login via the Sports Tracker backend;
  sleep / recovery / 24-7 activity / workout sensors; lifetime stats; derived
  training-load (CTL/ATL/TSB, ACWR) and recovery (HRV/RHR baselines, Readiness)
  metrics; brand assets.
