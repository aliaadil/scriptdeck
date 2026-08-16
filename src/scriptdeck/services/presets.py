from __future__ import annotations

PRESETS: list[dict[str, str]] = [
    {"id": "every-15m",   "label": "Every 15 min",      "cron": "*/15 * * * *"},
    {"id": "hourly",      "label": "Hourly",            "cron": "0 * * * *"},
    {"id": "daily-9",     "label": "Daily @ 9:00",      "cron": "0 9 * * *"},
    {"id": "weekdays-17", "label": "Weekdays @ 17:00",  "cron": "0 17 * * 1-5"},
    {"id": "mondays-8",   "label": "Mondays @ 08:00",   "cron": "0 8 * * 1"},
    {"id": "first-month", "label": "First of month",    "cron": "0 0 1 * *"},
]
