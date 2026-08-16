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

# One-off deep scan used ONLY to seed the VO2max / fitness-age sensors. Suunto
# derives those from runs and walks alone, so an account that mostly rides can go
# well over a year without a fresh reading (confirmed live: the newest reading was
# 308 days old). Runs once, and only while no reading is known.
FITNESS_LOOKBACK_DAYS = 730

# Backfill buffer for the hourly statistics import (activity + workout heartrates
# + recovery). Larger than ACTIVITY_LOOKBACK_DAYS (which the 15-min fast poll uses
# only for "today") so a watch->app sync delayed up to this many days still fills
# the missed hours retroactively. Re-imported idempotently every daily cycle.
STATS_LOOKBACK_DAYS = 5

# The Sports Tracker workouts list is occasionally eventually-consistent: a whole
# workout can vanish from one response and reappear the next cycle, which wobbles
# every workout-derived sensor (counts, weekly volume, CTL/ATL/TSB, statistics).
# We keep a per-key cache and retain a transiently-missing workout for this grace
# window so a single flaky fetch can't drop it; a genuinely deleted workout falls
# out once it has been absent longer than this.
WORKOUT_CACHE_GRACE_HOURS = 24

# The 24/7 activity stream reports `energyConsumption` in JOULES, not calories.
# Confirmed live 2026-07-21: every per-interval value is an exact multiple of
# 4186.8 (4186.75, 8373.5, 12560.25, 16747.25, 20934.0, 46054.75, ...), i.e. the
# backend sends whole kilocalories converted to joules. 4186.8 J = 1 kcal
# (International Table). We used to divide by 1000, which inflated every energy
# figure by ~4.19x.
JOULES_PER_KCAL = 4186.8

PLATFORMS = ["sensor", "binary_sensor", "calendar"]

# Fired on the Home Assistant bus when the daily coordinator first sees a workout
# key it has never seen before, so automations can react to a finished workout
# without polling a sensor's state. The very first cycle after a restart only
# SEEDS the known-key set (the fetch window holds ~90 days of history, and
# replaying all of it as "new" would fire a burst of bogus events).
EVENT_NEW_WORKOUT = f"{DOMAIN}_new_workout"

# ...and even then, only a workout that STARTED this recently is announced. A
# genuinely old record can still surface for the first time (pagination cut it
# off, or the upstream list was mid-reindex), and an automation firing "new
# workout" for a two-month-old ride is noise. Older ones are recorded silently.
NEW_WORKOUT_MAX_AGE_DAYS = 7

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
