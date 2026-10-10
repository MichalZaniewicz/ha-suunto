"""Constants for the Suunto App (unofficial) integration."""

from __future__ import annotations

DOMAIN = "suunto_app"

# Sports Tracker hosts (the backend the Suunto app uses).
API_BASE = "https://api.sports-tracker.com/apiserver/v1/"
TIMELINE_BASE = "https://247.sports-tracker.com/"

# Config entry keys
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_SESSION_KEY = "session_key"
CONF_SCAN_INTERVAL = "scan_interval"  # daily/history coordinator
CONF_FAST_SCAN_INTERVAL = "fast_scan_interval"  # live coordinator
# Commute savings: what the car you did NOT take would have burned.
CONF_FUEL_CONSUMPTION = "fuel_l_per_100km"
CONF_FUEL_PRICE = "fuel_price_per_litre"
DEFAULT_FUEL_CONSUMPTION = 7.0
DEFAULT_FUEL_PRICE = 6.5
# Tailpipe CO2 of a litre of petrol (kg) - the standard combustion figure.
CO2_KG_PER_LITRE = 2.31
# Suunto's own tag for a ride/run/walk it classified as a commute.
COMMUTE_TAG = "COMMUTE"
# User-defined gear (chain, tyres, shoes...) tracked by distance; a list of
# dicts in entry.options, managed by the options flow.
CONF_GEAR = "gear"
# Daily AI insight through Home Assistant's AI Task (see ai_insight.py): the
# ai_task entity to use (unset = feature off), the user's own notes for the
# prompt, and the hour to run at if the morning sync never came.
CONF_AI_TASK_ENTITY = "ai_task_entity"
CONF_AI_CONTEXT = "ai_extra_context"
CONF_AI_HOUR = "ai_fallback_hour"
DEFAULT_AI_HOUR = 10

# Defaults - two cadences: live data (HR/steps) refreshes often; heavy history
# (sleep, workouts, derived metrics) refreshes infrequently.
DEFAULT_SCAN_INTERVAL_MINUTES = 60
MIN_SCAN_INTERVAL_MINUTES = 15
DEFAULT_FAST_SCAN_INTERVAL_MINUTES = 15
MIN_FAST_SCAN_INTERVAL_MINUTES = 5
REQUEST_TIMEOUT = 45

# Look-back windows. Sleep + workouts pull extra history to feed the HRV/RHR
# baselines and the CTL/ATL training-load model.
SLEEP_LOOKBACK_DAYS = 60
RECOVERY_LOOKBACK_DAYS = 5
ACTIVITY_LOOKBACK_DAYS = 2
WORKOUTS_LOOKBACK_DAYS = 90

# How many of the most recent workouts ride along in the recent_workouts
# sensor's attribute. Sliced from norm_workouts, which is already the full
# 90-day window fetched above - no extra cost to raising this. Needs to
# comfortably outlast the 6-week window suunto-cards' Activity Calendar card
# builds from this same attribute: 15 undercounted for anyone training more
# than ~2-3x/week, leaving weeks of the calendar looking falsely inactive
# (confirmed live - reported by a user whose calendar showed 4 empty weeks
# then 2 active ones, exactly the shape a frequent exerciser's top-15 window
# produces). 60 covers 6 weeks at up to ~1.4 workouts/day.
RECENT_WORKOUTS_LIMIT = 60

# Reach of the deep history scan that seeds what the 90-day window cannot see:
# all-time records, this year's totals/records, and VO2max / fitness age (Suunto
# derives those from runs and walks alone, so an account that mostly rides can go
# well over a year without a fresh reading - confirmed live: the newest reading
# was 308 days old). One scan feeds all three, and its result is kept in a Store,
# so a restart does not repeat it.
FITNESS_LOOKBACK_DAYS = 730
# The stored seed is redone after this many days anyway, so a workout deleted or
# edited in the app (a GPS glitch that set a "record") does not live on forever.
DEEP_SCAN_REFRESH_DAYS = 7

# Backfill buffer for the hourly statistics import (activity + workout heartrates
# + recovery). Larger than ACTIVITY_LOOKBACK_DAYS (which the 15-min fast poll uses
# only for "today") so a watch->app sync delayed up to this many days still fills
# the missed hours retroactively. Re-imported idempotently every daily cycle.
STATS_LOOKBACK_DAYS = 5

# Cap on the number of GPS vertices exposed in the last workout's decoded route
# (see coordinator._downsample_route). A long workout's polyline can carry well
# over a thousand points - far more precision than a dashboard card needs to
# draw a recognizable route shape, and this attribute is excluded from the
# recorder (SuuntoAppSensor._unrecorded_attributes) but still sent to
# every connected frontend on each state update, so it stays deliberately small.
MAX_ROUTE_POINTS = 300

# The Sports Tracker workouts list is occasionally eventually-consistent: a whole
# workout can vanish from one response and reappear the next cycle, which wobbles
# every workout-derived sensor (counts, weekly volume, CTL/ATL/TSB, statistics).
# We keep a per-key cache and retain a transiently-missing workout for this grace
# window so a single flaky fetch can't drop it; a genuinely deleted workout falls
# out once it has been absent longer than this.
WORKOUT_CACHE_GRACE_HOURS = 24

# A workout's top-level `recoveryTime` tops out at exactly 5 days. Seen live
# (2026-09-21) on a 7.5 h hike recorded without heart rate: top-level 432000 s,
# while SummaryExtension.recoveryTime said 10200 s. Without HR the watch has no
# real intensity signal, so the capped value is not trusted for such workouts.
RECOVERY_TIME_CAP_S = 432_000

# How far ahead the form forecast projects CTL/ATL/TSB under zero load. With
# time constants of 42/7 days, form peaks roughly two weeks into a full rest,
# so four weeks always contains the peak.
FORECAST_DAYS = 28

# current_hr falls back to the newest 24/7 record that carries a heart rate, but
# only if it is at most this far behind the newest record overall. Longer gaps
# (a long workout, watch off the wrist) read as unknown rather than stale.
CURRENT_HR_MAX_GAP_MINUTES = 60

# The profile (weight/height/birthdate for BMR) barely changes, so it is fetched
# once a day on the fast coordinator instead of on every 15-min poll.
PROFILE_REFRESH_HOURS = 24

# The 24/7 activity stream reports `energyConsumption` in JOULES, not calories.
# Confirmed live 2026-07-21: every per-interval value is an exact multiple of
# 4186.8 (4186.75, 8373.5, 12560.25, 16747.25, 20934.0, 46054.75, ...), i.e. the
# backend sends whole kilocalories converted to joules. 4186.8 J = 1 kcal
# (International Table). We used to divide by 1000, which inflated every energy
# figure by ~4.19x.
JOULES_PER_KCAL = 4186.8

PLATFORMS = ["sensor", "binary_sensor", "calendar", "button", "switch"]

# Fired on the Home Assistant bus when the daily coordinator first sees a workout
# key it has never seen before, so automations can react to a finished workout
# without polling a sensor's state. The very first cycle after a restart only
# SEEDS the known-key set (the fetch window holds ~90 days of history, and
# replaying all of it as "new" would fire a burst of bogus events).
EVENT_NEW_WORKOUT = f"{DOMAIN}_new_workout"
# Fired once when a new sleep night first reaches us (i.e. after the morning
# watch sync), so a "good morning" automation can react to last night's sleep.
EVENT_WOKE_UP = f"{DOMAIN}_woke_up"
# Fired after every successful AI insight run (see ai_insight.py), carrying the
# whole review plus labels in the HA language, so a blueprint can send it.
EVENT_AI_INSIGHT = f"{DOMAIN}_ai_insight"

# ...and even then, only a workout that STARTED this recently is announced. A
# genuinely old record can still surface for the first time (pagination cut it
# off, or the upstream list was mid-reindex), and an automation firing "new
# workout" for a two-month-old ride is noise. Older ones are recorded silently.
NEW_WORKOUT_MAX_AGE_DAYS = 7

# The watch syncs in the middle of the night too, so the first fragment of a
# night can reach us at 2 a.m. while the athlete is still asleep. A night only
# counts as finished (woke-up event, AI insight) once its last fragment ends at
# or after this local hour on the morning after; until then more is expected.
EARLIEST_WAKE_HOUR = 4
# The hour alone is not enough: a brief wake at 4:17 ends a fragment too, and
# the sync after it looks like a finished night while the athlete sleeps on
# until 7 (seen live 2026-10-09). So the 24/7 stream must also show the
# athlete up and moving: at least this many steps after the wake time. A
# bathroom trip stays well below it.
AWAKE_MIN_STEPS = 200

# activityId -> label (partial; unknown ids fall back to "Activity <id>").
ACTIVITY_NAMES: dict[int, str] = {
    0: "Walking",
    1: "Running",
    2: "Cycling",
    3: "Cross-country skiing",
    10: "Mountain biking",
    11: "Hiking",
    13: "Alpine skiing",
    14: "Paddling",
    15: "Rowing",
    16: "Golf",
    21: "Swimming",
    22: "Trail running",
    23: "Gym",
    24: "Nordic walking",
    29: "Climbing",
    30: "Snowboarding",
    33: "Soccer",
    38: "Volleyball",
    51: "Yoga",
    52: "Indoor cycling",
    53: "Treadmill running",
    70: "Trekking",
    72: "Kayaking",
    76: "Strength training",
    77: "Walking",
}


def activity_name(activity_id: int | None) -> str | None:
    """Map a Suunto activityId to a label."""
    if activity_id is None:
        return None
    return ACTIVITY_NAMES.get(activity_id, f"Activity {activity_id}")


# Foot-based activities where "stride length" (distance per cadence cycle) is
# meaningful. For others (e.g. cycling, where cadence is pedal RPM) it is not a
# stride, so the sensor is left empty rather than mislabeled.
FOOT_ACTIVITY_IDS: frozenset[int] = frozenset(
    {1, 11, 22, 24, 53, 59, 60, 65, 70, 77}
)

# Standard race distances (metres) for the best-effort sensor - foot-based
# activities only, same gating as cadence_spm/stride_length above. Ordered
# shortest-first purely for readable debug logging; dict iteration order
# doesn't otherwise matter here.
STANDARD_DISTANCES_M: dict[str, int] = {
    "1k": 1000,
    "5k": 5000,
    "10k": 10000,
    "half_marathon": 21097,
    "marathon": 42195,
}
