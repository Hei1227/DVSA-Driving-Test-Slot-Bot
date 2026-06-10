# DVSA Driving Test Slot Bot

> Automatically finds and books a UK practical driving test slot the moment one becomes available — fully hands-free

Built on [patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) (an undetected fork of Playwright), the bot navigates the DVSA booking site like a real user, handles bot-detection challenges automatically, and notifies you via Discord the instant a slot is reserved.

---

## Features

- **Fully automated booking flow** — selects test type, accepts the declaration, fills in your licence number, answers the eligibility questions, and clicks through every page without any manual input
- **Postcode mode (recommended)** — one search per cycle shows every nearby centre's earliest available date directly in the results, so the bot only opens a centre's calendar when that date falls inside your range. Far fewer requests, far less likely to get challenged
- **Multi-centre scanning** — classic mode monitors as many test centres as you want, in priority order, on every cycle
- **Preferred time selection** — picks the slot closest to your preferred time of day on the earliest available date
- **CAPTCHA awareness** — detects hCaptcha challenges and pauses with a clear on-screen prompt; resumes automatically once solved
- **Imperva / Incapsula handling** — waits up to 90–120 s on pages where bot-detection challenges auto-resolve
- **Human-like behaviour** — warm-up browsing before DVSA, randomised delays, Bezier-curve mouse movement (via `humanization-playwright`)
- **Session persistence** — uses a dedicated Chrome profile that accumulates cookies and history between runs, exactly the lived-in fingerprint Imperva expects from a real user
- **Discord notifications** — sends a formatted message the moment a slot is reserved
- **Retry loop** — checks availability every 2.5–5 minutes until a slot is found, with an automatic cooldown after any bot challenge

---

## How it works

### Full automated flow

```
Launch Chrome (undetected, persistent profile)
    │
    ▼
Warm up — visit a random selection of UK sites with human-like scrolling
    │
    ▼
Navigate to DVSA booking site
    │
    │
    │
    ▼
[PAGE] Choose test type
    └─ Bot selects "Car" and continues
    │
    ▼
[PAGE] Candidate declaration
    └─ Bot ticks "I confirm I am the learner and agree to the terms"
    └─ Bot clicks "Agree and continue"
    │
    ▼
[PAGE] Licence details
    └─ Bot fills your driving licence number
    └─ Bot selects "No" for extended test
    └─ Bot selects "No" for special requirements
    └─ Bot submits
    │
    ▼
[PAGE] "Choosing your date and test centre" info page  
    └─ Bot clicks Continue
    │
    ▼
[PAGE] Test preferences
    └─ Bot enters your DATE_FROM as the preferred start date
    └─ Bot submits
    │
    ▼
┌─────────────────────────────────────────────────┐
│            SCAN LOOP (repeats every 2.5–5 min)  │
│                                                 │
│  Postcode mode (recommended):                   │
│    ├─ Search once by POSTCODE                   │
│    ├─ Read each centre's availability hint      │
│    │    ("available tests around DD/MM/YYYY")   │
│    └─ Only open centres whose hint date is      │
│         inside your DATE_FROM–DATE_TO range     │
│                                                 │
│  Centres mode: open every centre in             │
│  centres.yaml each cycle                        │
│                                                 │
│  For each opened centre:                        │
│    ├─ Read the BookingCalendar                  │
│    │    └─ Find earliest bookable date in range │
│    ├─ Click that date                           │
│    ├─ Load the time slots for that day          │
│    ├─ Pick slot closest to PREFERRED_TIME       │
│    ├─ Click the slot label (triggers DVSA JS)   │
│    ├─ Wait for submit button to enable          │
│    └─ Submit                                    │
│                                                 │
│  If booked → send Discord notification          │
│              pause for payment → done           │
│                                                 │
│  If not found → wait, then repeat loop          │
│  If challenged → alert via Discord, wait for    │
│                  you to solve it, then cool down│
└─────────────────────────────────────────────────┘
```

---

## Requirements

| | |
|---|---|
| **OS** | Windows 10/11 or macOS |
| **Python** | 3.11 or newer |
| **Browser** | Google Chrome (standard install) |


---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/Driving_Test_Booking_Automation_Bot.git
cd Driving_Test_Booking_Automation_Bot
```

### 2. Create a virtual environment

**Windows:**

```bash
python -m venv venv
venv\Scripts\activate
```

**macOS:**

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4. Install the patchright browser

```bash
patchright install chromium
```

### 5. Chrome profile folder

The bot stores your DVSA login session in a dedicated Chrome profile.
The folder is **created automatically on first run** at:

- **Windows:** `C:\chrome-profile`
- **macOS:** `~/chrome-profile`

> You can use any path — set `PROFILE_PATH` in your `.env` file or edit the default in `config.py`.

---

## Configuration

### `config.py` — main settings file

Open `config.py` and adjust the values for your situation:

```python
# Path to the dedicated Chrome profile (stores your DVSA session).
# Defaults to C:\chrome-profile on Windows, ~/chrome-profile on macOS.
# Override via PROFILE_PATH in .env if you want a different location.

# Date range to search — DD/MM/YY format matching the DVSA site
DATE_FROM = "01/07/26"
DATE_TO   = "31/08/26"

# Search mode — "postcode" (recommended) or "centres"
# Postcode mode: one search per cycle; the results page already shows each
# nearby centre's earliest available date, so the bot only opens a centre
# when that date is inside your range. centres.yaml acts as a filter
# (leave it empty to consider every centre in the results).
# Centres mode: opens every centre in centres.yaml each cycle.
SEARCH_MODE = "postcode"
POSTCODE = "SW1A"

# Your driving licence number — auto-filled on the Licence details page
# Leave as "" to type it manually in the browser
DRIVING_LICENCE_NUMBER = os.environ.get("DRIVING_LICENCE_NUMBER", "")

# Preferred slot time — bot picks the nearest available slot on the day
# Use "HH:MM" (24-hour). Set to "" or None to always take the earliest slot.
PREFERRED_TIME = "11:00"

# Discord webhook — paste the URL here or set it in .env (recommended)
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")
```

### `centres.yaml` — test centres to monitor

List the DVSA test centres you want the bot to check, using the **exact names** as they appear on the DVSA booking site. The bot searches them in order on every cycle.

```yaml
centres:
  - Isleworth (Fleming Way)
  - Yeading (London)
  - Greenford (London)
```

> To find the exact name: go to the DVSA site manually, search for your centre, and copy the name shown in the results.

### `.env` — secrets (recommended)

Sensitive values like your Discord webhook and driving licence number are better kept out of `config.py`. Copy `.env.example` to `.env` and fill it in:

```bash
cp .env.example .env
```

```env
# .env
DISCORD_WEBHOOK=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
DRIVING_LICENCE_NUMBER=SIGMABOI6767
```

The `.env` file is listed in `.gitignore` and will never be committed.

---

## Running the bot

Make sure your virtual environment is active, then:

**Windows:**

```bash
venv\Scripts\activate
python main.py
```

**macOS:**

```bash
source venv/bin/activate
python3 main.py
```

### First run

1. Chrome opens and navigates to the DVSA booking site.
2. The site may show an Imperva / hCaptcha challenge before letting you through — solve it in the browser window if prompted.
3. Once past any challenge you land on the **Choose test type** page and the bot takes over completely from there.

> The Chrome profile at `PROFILE_PATH` stores your DVSA session between runs, so the bot picks up right at the booking flow each time without any manual steps.

### Subsequent runs

Same as the first run — Chrome opens, the bot lands on the Choose test type page (or handles any challenge that appears), and runs the full automated flow from there.

---

## CAPTCHA and bot-detection handling

The DVSA site uses two layers of bot protection:

| Challenge | How the bot handles it |
|---|---|
| **Imperva / Incapsula** (JavaScript challenge) | Auto-resolves in 30–60 s. The bot waits up to 90–120 s on the affected pages and prints a notice in the console. No action needed. |
| **hCaptcha** (image challenge) | Detected by the bot. It prints a warning, pauses, and waits for you to solve the challenge in the browser window. The bot resumes automatically once you pass it. |

---

## Project structure

```
Driving_Test_Booking_Automation_Bot/
│
├── main.py                       Entry point — starts the browser and runs the flow
├── config.py                     All user settings (dates, profile path, preferences)
├── centres.yaml                  List of DVSA test centres to monitor
├── requirements.txt              Python package dependencies
├── .env.example                  Template for secret environment variables
│
└── src/
    ├── auth.py                   Browser launch, warm-up browsing, DVSA navigation,
    │                             startup data clearing, login handling
    ├── slot_checker.py           The full booking engine:
    │                               - Declaration acceptance
    │                               - Licence details form
    │                               - "Choosing date" info page
    │                               - Date form, centre search
    │                               - BookingCalendar reading
    │                               - Slot selection and submission
    │                               - Retry loop
    └── discord_notification.py   Sends a Discord webhook message on successful booking
```

---

## Troubleshooting

**Bot prints "Booking calendar not found on page"**
The centre you searched for has no bookable slots at all, or the page took too long to load. The bot will move on to the next centre and retry on the next cycle. This is normal.

**Bot prints "None in range DATE_FROM–DATE_TO"**
The centre has bookable slots but all of them fall outside your configured date range. Widen your `DATE_TO` in `config.py`.

**Bot prints "CAPTCHA detected"**
Solve the hCaptcha in the browser window. The bot is waiting and will continue on its own once you pass it.

**Browser closes immediately / crashes on startup**
Make sure Chrome is installed and the `PROFILE_PATH` location is writable. Run `patchright install chromium` if you have not done so.

**Discord notification not received**
Check that `DISCORD_WEBHOOK` is set correctly in `.env` or `config.py`. The bot prints a warning at startup if the webhook is missing.

**Slot found but not booked (submit button stays grey)**
This should be fixed in the current version. The bot now clicks the slot `<label>` element (not the raw radio input) to correctly trigger the DVSA JavaScript that enables the submit button.

---

## Dependencies

| Package | Purpose |
|---|---|
| `patchright` | Undetected Chromium browser automation (fork of Playwright) |
| `pyyaml` | Reads `centres.yaml` |
| `aiohttp` | Async HTTP client for Discord webhook notifications |
| `python-dotenv` | Loads secrets from the `.env` file |
| `humanization-playwright` | Bezier-curve mouse movement for human-like interaction (optional) |
| `tzdata` | IANA timezone database — needed on Windows for UK local time maths (harmless no-op on macOS, which ships its own) |

---

## Disclaimer

This tool is intended for **personal use only** — to help you book your *own* driving test faster.
Automated access to the DVSA website may conflict with their terms of service. Use responsibly and at your own risk.