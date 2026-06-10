import os
from dotenv import load_dotenv

load_dotenv()

# ── Browser ──────────────────────────────────────────────────────────────────
# Set to "chrome" (only Chrome is supported via patchright).
BROWSER_TYPE = "chrome"

# Path to the dedicated Chrome profile used by the bot.
# This profile stores the DVSA login session so you only sign in once.
# It can live anywhere you like — the folder is created automatically on
# first run.  Defaults: C:\chrome-profile on Windows, ~/chrome-profile on
# macOS/Linux.  Override via PROFILE_PATH in .env or by editing below.
PROFILE_PATH = os.environ.get("PROFILE_PATH") or (
    r"C:\chrome-profile" if os.name == "nt"
    else os.path.expanduser("~/chrome-profile")
)

# ── Notifications ─────────────────────────────────────────────────────────────
# Discord webhook URL — receive a DM the moment a slot is booked.
# Set in .env as DISCORD_WEBHOOK=https://discord.com/api/webhooks/...
# Leave blank to disable notifications.
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")

# ── Search window ─────────────────────────────────────────────────────────────
# DD/MM/YY format, matching the DVSA site's date field.
DATE_FROM = "01/07/26"
DATE_TO   = "31/08/26"

# ── Search mode ───────────────────────────────────────────────────────────────
# "postcode" — recommended.  One search per cycle by POSTCODE.  The results
#              page already shows each nearby centre's earliest available date
#              ("available tests around 23/10/2026"), so the bot only opens a
#              centre's calendar when that date falls inside your range.
#              Far fewer requests = far less likely to get challenged.
#              centres.yaml acts as a filter: only listed centres are opened
#              (leave the list empty to consider every centre in the results).
# "centres"  — classic mode: searches each centre in centres.yaml by name,
#              opening its calendar every cycle regardless of availability.
SEARCH_MODE = "postcode"

# Home postcode (full or partial, e.g. "SW1A") — used when SEARCH_MODE = "postcode".
POSTCODE = "SW1A"

# ── Driving licence ───────────────────────────────────────────────────────────
# Auto-filled on the Licence details page.
# Set here directly OR via DRIVING_LICENCE_NUMBER=... in your .env file.
# Leave as "" to type it manually in the browser.
DRIVING_LICENCE_NUMBER = os.environ.get("DRIVING_LICENCE_NUMBER", "")

# ── Preferred slot time ───────────────────────────────────────────────────────
# 24-hour "HH:MM".  On the earliest available date the bot picks the slot
# whose start time is closest to this value.
# Set to None or "" to always take the earliest available slot.
PREFERRED_TIME = "11:00"
