# Changelog

Notable changes per release. Releases are published on GitHub (HACS reads them);
beta pre-releases are tagged `X.Y.ZbN`.

## 1.0.14
- **Peak Training Effect** sensor (`last_pte`) - Suunto's own 1..5 rating of how
  hard the last session hit you, read from the workout's `SummaryExtension`.
- **Descent, climb/descend times and altitude range** for the last workout:
  `last_descent`, `last_ascent_time`, `last_descent_time`, `last_min_altitude`
  and `last_max_altitude`. Indoor sessions carry no barometer data, so the
  altitude pair stays unknown there rather than reporting sea level; a flat
  outdoor workout correctly reads 0 m of descent.
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
