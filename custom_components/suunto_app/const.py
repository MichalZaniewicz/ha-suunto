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

# Defaults — two cadences: live data (HR/steps) refreshes often; heavy history
# (sleep, workouts, derived metrics) refreshes infrequently.
DEFAULT_SCAN_INTERVAL_MINUTES = 60
MIN_SCAN_INTERVAL_MINUTES = 15
DEFAULT_FAST_SCAN_INTERVAL_MINUTES = 15
MIN_FAST_SCAN_INTERVAL_MINUTES = 5
REQUEST_TIMEOUT = 45

# Look-back windows. Sleep + workouts pull extra history to feed the HRV/RHR
# baselines and the CTL/ATL training-load model.
SLEEP_LOOKBACK_DAYS = 60
RECOVERY_LOOKBACK_DAYS = 4
ACTIVITY_LOOKBACK_DAYS = 2
WORKOUTS_LOOKBACK_DAYS = 90

# The Sports Tracker workouts list is occasionally eventually-consistent: a whole
# workout can vanish from one response and reappear the next cycle, which wobbles
# every workout-derived sensor (counts, weekly volume, CTL/ATL/TSB, statistics).
# We keep a per-key cache and retain a transiently-missing workout for this grace
# window so a single flaky fetch can't drop it; a genuinely deleted workout falls
# out once it has been absent longer than this.
WORKOUT_CACHE_GRACE_HOURS = 24

PLATFORMS = ["sensor"]

# activityId -> label (partial; unknown ids fall back to "Activity <id>").
ACTIVITY_NAMES: dict[int, str] = {
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
    51: "Yoga",
    52: "Indoor cycling",
    53: "Treadmill running",
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
