import asyncio
import random
import re
import yaml
from datetime import datetime
from typing import Optional
from playwright.async_api import Page
from src.discord_notification import send_discord_notification, send_captcha_alert

try:
    from zoneinfo import ZoneInfo
    _UK_TZ = ZoneInfo("Europe/London")
except Exception:
    _UK_TZ = None   # tzdata not installed — will use UTC+1 fallback

# All body IDs the DVSA booking flow can legitimately have.
# If the page body ID is not in this set (and is non-empty), we're most likely
# on an Imperva / Incapsula challenge page or have been redirected away.
_KNOWN_DVSA_PAGES = {
    "page-choose-test-type",
    "page-candidate-declaration",
    "page-driving-licence-number",
    "page-choosing-date-and-test-centre",
    "page-test-preferences",
    "page-test-centre-search",
    "page-available-time",
    "page-confirmation",
}


def _slot_minutes(timestamp_ms: int) -> int:
    """Convert a slot Unix-millisecond timestamp to minutes-since-midnight (UK local time)."""
    if _UK_TZ is not None:
        dt = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=_UK_TZ)
        return dt.hour * 60 + dt.minute
    # Fallback: assume BST (UTC+1) — covers Jul–Oct which is our typical search window
    total_minutes = (timestamp_ms // 1000 + 3600) // 60
    return total_minutes % (24 * 60)


def _parse_preferred_minutes(time_str: Optional[str]) -> Optional[int]:
    """Parse 'HH:MM' → minutes since midnight, or None if blank/invalid."""
    if not time_str:
        return None
    try:
        h, m = time_str.strip().split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None

try:
    from humanization import Humanization, HumanizationConfig
    _HUMANIZATION_AVAILABLE = True
except ImportError:
    _HUMANIZATION_AVAILABLE = False
    print("WARNING: humanization-playwright not installed. Falling back to basic mouse movement.")
    print("         Run: pip install humanization-playwright")


def load_centres():
    with open("centres.yaml", "r") as f:
        return yaml.safe_load(f)["centres"]


def parse_date(date_str):
    return datetime.strptime(date_str, "%d/%m/%y")


def date_in_range(data_date, date_from, date_to):
    try:
        d = datetime.strptime(data_date, "%Y-%m-%d")
        return parse_date(date_from) <= d <= parse_date(date_to)
    except Exception:
        return False


def _make_humanizer(page: Page):
    if not _HUMANIZATION_AVAILABLE:
        return None
    config = HumanizationConfig(
        humanize=True,
        characters_per_minute=220,
        backspace_cpm=300,
        stealth_mode=True,
    )
    return Humanization(page, config)


# ---------------------------------------------------------------------------
# Human typing — NO intentional typos, just variable speed
# ---------------------------------------------------------------------------

async def human_type(page: Page, selector: str, text: str):
    """
    Types text at human-like speed.
    - Tries humanization-playwright first (Bezier move + variable CPM)
    - Falls back to: click ONCE to focus, then keyboard.type() per char
      (keyboard.type never re-focuses, so Backspace always acts on the right field)
    """
    h = _make_humanizer(page)
    if h is not None:
        try:
            locator = page.locator(selector).first
            await h.type_at(locator, text)
            return
        except Exception as e:
            print(f"  [humanizer] type_at failed ({e.__class__.__name__}), using fallback")

    # Fallback: single click to focus, then keyboard.type per char.
    # keyboard.type() does NOT shift focus — Backspace stays on this field.
    # NO intentional-typo simulation: it caused the backspace-on-wrong-field bug.
    await page.click(selector)
    await asyncio.sleep(random.uniform(0.3, 0.7))
    for char in text:
        await page.keyboard.type(char)
        await asyncio.sleep(random.uniform(0.07, 0.20))
        if random.random() < 0.08:
            await asyncio.sleep(random.uniform(0.25, 0.6))
    await asyncio.sleep(random.uniform(0.3, 0.8))


# ---------------------------------------------------------------------------
# Human mouse movement / click
# ---------------------------------------------------------------------------

async def move_mouse_naturally(page: Page, locator=None):
    h = _make_humanizer(page)
    if h is not None:
        try:
            target = locator if locator is not None else page.locator("body").first
            await h.move_to(target, offset_x=random.randint(-40, 40), offset_y=random.randint(-20, 20))
        except Exception:
            pass
        return
    try:
        for _ in range(random.randint(2, 4)):
            await page.mouse.move(
                random.randint(300, 800),
                random.randint(200, 500),
                steps=random.randint(10, 25),
            )
            await asyncio.sleep(random.uniform(0.1, 0.3))
    except Exception:
        pass


async def human_click(page: Page, locator):
    h = _make_humanizer(page)
    if h is not None:
        try:
            await h.click_at(locator)
            return
        except Exception:
            pass
    await locator.click()


# ---------------------------------------------------------------------------
# CAPTCHA / human-verification detection
# ---------------------------------------------------------------------------

async def _is_captcha_visible(page: Page) -> bool:
    """
    Return True if any kind of bot-detection challenge is active.

    Covers:
      - hCaptcha widget (iframe or .h-captcha div)
      - Imperva / Incapsula full-page challenge (element IDs and URL patterns)
      - PerimeterX challenge (#px-captcha)
      - Generic "checking your browser" / "access denied" page titles
    """
    try:
        # hCaptcha widget
        if await page.locator("iframe[src*='hcaptcha'], .h-captcha").count() > 0:
            return True
        # Imperva / Incapsula / PerimeterX challenge elements
        if await page.locator("#incapsula-resource, #sec-cpt-if, #px-captcha, #challenge-form").count() > 0:
            return True
        # Challenge URL patterns (Imperva redirects)
        url = page.url.lower()
        if "_incapsula_" in url or "/_challenge" in url or "distil_r_captcha" in url:
            return True
        # Generic challenge page titles
        title = (await page.title()).lower()
        if any(kw in title for kw in ["access denied", "please wait", "checking your browser", "just a moment"]):
            return True
        return False
    except Exception:
        return False


async def _is_on_unknown_page(page: Page) -> bool:
    """
    Return True if the page has a non-empty body ID that isn't a known DVSA page.
    This is a secondary signal that we've been redirected to a challenge page
    that doesn't match any of the heuristics in _is_captcha_visible.
    """
    try:
        body_id = await page.locator("body").get_attribute("id") or ""
        return bool(body_id) and body_id not in _KNOWN_DVSA_PAGES
    except Exception:
        return False


async def wait_for_captcha_clear(page: Page, discord_webhook: Optional[str] = None):
    """
    Blocks if any bot-detection challenge is active OR if the bot finds itself on
    an unrecognised (non-DVSA) page — both are signs of a challenge redirect.

    On first detection:
      - Prints a warning to the console
      - Sends a Discord alert (if webhook is configured)
    Keeps polling every 2 s until back on a normal DVSA page.
    No-op if everything looks fine.
    """
    captcha = await _is_captcha_visible(page)
    unknown = await _is_on_unknown_page(page)

    if not captcha and not unknown:
        return

    reason = "CAPTCHA / human verification" if captcha else "challenge / redirect page"
    print("\n" + "=" * 60)
    print(f"  ⚠️  BOT CHALLENGE DETECTED ({reason})")
    print("  Please check the browser window and solve any challenge.")
    print("  The bot will resume automatically once the page clears.")
    print("=" * 60 + "\n")

    if discord_webhook:
        await send_captcha_alert(discord_webhook)

    # Poll until no challenge AND back on a known DVSA page (or blank body ID)
    while True:
        await asyncio.sleep(2)
        if await _is_captcha_visible(page):
            continue
        if await _is_on_unknown_page(page):
            continue
        break

    print("✓ Challenge cleared — resuming.\n")


# ---------------------------------------------------------------------------
# Step 1b — Accept the candidate declaration
# ---------------------------------------------------------------------------

async def accept_declaration(page: Page):
    """
    Handles body#page-candidate-declaration.

    Ticks the 'I confirm I am the learner and agree to the terms and conditions'
    checkbox, waits for DVSA JS to enable the submit button, then clicks
    'Agree and continue'.
    """
    try:
        await asyncio.sleep(random.uniform(0.8, 1.8))
        await move_mouse_naturally(page)

        # Click the visible <label> — the raw <input type="checkbox"> is hidden
        label = page.locator("label[for='candidate-declaration']").first
        await label.wait_for(state="visible", timeout=8000)
        await human_click(page, label)
        await asyncio.sleep(random.uniform(0.5, 1.0))

        # JS removes the 'button-lookdisabled' class once checkbox is ticked
        try:
            await page.wait_for_selector(
                "#candidate-declaration-submit:not(.button-lookdisabled)", timeout=5000
            )
        except Exception:
            pass  # try clicking anyway

        submit = page.locator("#candidate-declaration-submit").first
        await move_mouse_naturally(page, locator=submit)
        await asyncio.sleep(random.uniform(0.5, 1.2))
        await human_click(page, submit)
        await page.wait_for_load_state("domcontentloaded")
        print("  ✓ Declaration accepted.")
    except Exception as e:
        print(f"  Error accepting declaration: {e}")


# ---------------------------------------------------------------------------
# Step 1c — Fill driving licence details
# ---------------------------------------------------------------------------

async def fill_licence_details(page: Page, licence_number: str):
    """
    Handles body#page-driving-licence-number.

    Fills the driving licence number, ensures 'No' is chosen for the
    extended-test and special-requirements questions, then submits.
    """
    if not licence_number:
        print("  DRIVING_LICENCE_NUMBER not set in config — skipping auto-fill.")
        return
    try:
        await asyncio.sleep(random.uniform(0.8, 1.8))
        await move_mouse_naturally(page)

        # --- Driving licence number ---
        lic = page.locator("#driving-licence").first
        await lic.wait_for(state="visible", timeout=8000)
        await page.fill("#driving-licence", "")
        await human_type(page, "#driving-licence", licence_number.upper())
        await asyncio.sleep(random.uniform(0.4, 0.8))

        # --- Extended test: 'No' is pre-checked; confirm just in case ---
        ext_no = page.locator("#extended-test-no").first
        if not await ext_no.is_checked():
            await human_click(page, page.locator("label[for='extended-test-no']").first)
            await asyncio.sleep(random.uniform(0.3, 0.6))

        # --- Special requirements: must explicitly choose 'None / No' ---
        spec_label = page.locator("label[for='special-needs-none']").first
        await spec_label.wait_for(state="visible", timeout=8000)
        await move_mouse_naturally(page, locator=spec_label)
        await asyncio.sleep(random.uniform(0.3, 0.7))
        await human_click(page, spec_label)
        await asyncio.sleep(random.uniform(0.4, 0.8))

        # --- Wait for DVSA JS to enable the submit button ---
        try:
            await page.wait_for_selector(
                "#driving-licence-submit:not(.button-lookdisabled)", timeout=5000
            )
        except Exception:
            pass

        submit = page.locator("#driving-licence-submit").first
        await move_mouse_naturally(page, locator=submit)
        await asyncio.sleep(random.uniform(0.5, 1.2))
        await human_click(page, submit)
        await page.wait_for_load_state("domcontentloaded")
        masked = licence_number[:4] + "*" * max(0, len(licence_number) - 4)
        print(f"  ✓ Licence details submitted ({masked})")
    except Exception as e:
        print(f"  Error filling licence details: {e}")


# ---------------------------------------------------------------------------
# Step 1d — "Choosing your date and test centre" info page
# ---------------------------------------------------------------------------

async def handle_choosing_date_page(page: Page):
    """
    Handles the body#page-choosing-date-and-test-centre info page (added in a
    recent DVSA upgrade).  Simply clicks 'Continue' to reach the date form.
    """
    try:
        await asyncio.sleep(random.uniform(0.8, 1.5))
        submit = page.locator("#choosing-date-test-centre-submit").first
        await submit.wait_for(state="visible", timeout=8000)
        await move_mouse_naturally(page, locator=submit)
        await asyncio.sleep(random.uniform(0.5, 1.2))
        await human_click(page, submit)
        await page.wait_for_load_state("domcontentloaded")
        print("  ✓ 'Choosing date' info page dismissed.")
    except Exception as e:
        print(f"  Error on choosing-date page: {e}")


# ---------------------------------------------------------------------------
# Step 1 — Select car test type
# ---------------------------------------------------------------------------

async def select_car_test(page: Page):
    # Allow up to 2 minutes — Imperva challenges can hold the page for 30-60 s
    # before auto-passing, or the user may need to solve it manually.
    print("Waiting for test-type page (if a verification challenge is showing, solve it now)...")
    try:
        await page.wait_for_selector("body#page-choose-test-type", timeout=120000)
        await asyncio.sleep(random.uniform(0.8, 1.8))
        await human_click(page, page.locator("input#test-type-car").first)
        print("Selected: Car test")
        await page.wait_for_load_state("domcontentloaded")
    except Exception as e:
        print(f"Test-type page not reached (already past it, or timed out): {e}")


# ---------------------------------------------------------------------------
# Step 2 — Auto-handle declaration → licence → info page → test preferences
# ---------------------------------------------------------------------------

async def wait_for_test_date_page(
    page: Page,
    timeout_minutes: int = 10,
    driving_licence: str = "",
    discord_webhook: Optional[str] = None,
):
    """
    State-machine that drives the bot through every page between
    'car test selected' and 'test preferences form':

      page-candidate-declaration        → accept
      page-driving-licence-number       → fill DLN, choose No×2, submit
      page-choosing-date-and-test-centre→ click Continue
      page-test-preferences             → return True (bot takes over date form)

    Polls every ~1.5 s.  If an hCaptcha verification widget is detected the
    user is warned and the bot keeps waiting — it resumes automatically once
    the challenge is solved.
    """
    print("\nBot is handling pre-booking setup automatically...")
    if not driving_licence:
        print("  (DRIVING_LICENCE_NUMBER not set — enter licence manually if prompted)\n")

    deadline = asyncio.get_event_loop().time() + timeout_minutes * 60
    handled: set = set()

    while asyncio.get_event_loop().time() < deadline:

        # ── CAPTCHA / human-verification check ──────────────────────────────
        # wait_for_captcha_clear is a no-op when no CAPTCHA is visible,
        # so it's safe to call on every iteration without extra flag logic.
        await wait_for_captcha_clear(page, discord_webhook)

        # ── Page detection ───────────────────────────────────────────────────
        try:
            body_id = await page.locator("body").get_attribute("id") or ""
        except Exception:
            await asyncio.sleep(1)
            continue

        # ── Terminal state ───────────────────────────────────────────────────
        if body_id == "page-test-preferences":
            print("Test date page reached — bot is taking over!")
            return True

        # ── Intermediate pages (handle each exactly once) ────────────────────
        if body_id == "page-candidate-declaration" and body_id not in handled:
            handled.add(body_id)
            print("  Accepting declaration...")
            await accept_declaration(page)
            continue

        if body_id == "page-driving-licence-number" and body_id not in handled:
            handled.add(body_id)
            print("  Filling licence details...")
            await fill_licence_details(page, driving_licence)
            continue

        if body_id == "page-choosing-date-and-test-centre" and body_id not in handled:
            handled.add(body_id)
            print("  Clicking through 'Choosing date' info page...")
            await handle_choosing_date_page(page)
            continue

        await asyncio.sleep(1.5)

    print(f"Timed out after {timeout_minutes} minutes. Please restart the bot.")
    return False


# ---------------------------------------------------------------------------
# Step 3 — Fill test date form
# ---------------------------------------------------------------------------

async def fill_test_date(page: Page, date_from: str):
    try:
        # After a session reset the 'Choosing date' info page may reappear —
        # wait for EITHER that OR the actual test-preferences form.
        try:
            await page.wait_for_selector(
                "body#page-test-preferences, body#page-choosing-date-and-test-centre",
                timeout=20000,
            )
        except Exception as e:
            print(f"Error filling test date (page not found): {e}")
            return

        body_id = await page.locator("body").get_attribute("id") or ""
        if body_id == "page-choosing-date-and-test-centre":
            print("  Handling 'Choosing date' info page (session reset)...")
            await handle_choosing_date_page(page)
            try:
                await page.wait_for_selector("body#page-test-preferences", timeout=15000)
            except Exception as e:
                print(f"Error reaching test-preferences after info page: {e}")
                return

        await asyncio.sleep(random.uniform(1.0, 2.5))
        await page.fill("#test-choice-calendar", "")
        await human_type(page, "#test-choice-calendar", date_from)
        await asyncio.sleep(random.uniform(0.8, 1.5))
        await human_click(page, page.locator("#driving-licence-submit").first)
        await page.wait_for_load_state("domcontentloaded")
        print(f"Submitted preferred date: {date_from}")
    except Exception as e:
        print(f"Error filling test date: {e}")


# ---------------------------------------------------------------------------
# Step 4 — Select a test centre
# ---------------------------------------------------------------------------

async def select_test_centre(page: Page, centre_name: str):
    try:
        await page.wait_for_selector("body#page-test-centre-search", timeout=15000)
        await asyncio.sleep(random.uniform(1.5, 3.0))
        await move_mouse_naturally(page)

        await page.fill("#test-centres-input", "")
        await human_type(page, "#test-centres-input", centre_name)

        submit = page.locator("#test-centres-submit").first
        await move_mouse_naturally(page, locator=submit)
        await asyncio.sleep(random.uniform(0.5, 1.2))
        await human_click(page, submit)
        await page.wait_for_load_state("domcontentloaded")

        await asyncio.sleep(random.uniform(1.5, 3.0))

        result = page.locator(f"a.test-centre-details-link:has(h4:text-is('{centre_name}'))").first
        if await result.count() == 0:
            result = page.locator(f"a.test-centre-details-link:has-text('{centre_name}')").first

        await result.wait_for(state="visible", timeout=8000)
        await move_mouse_naturally(page, locator=result)
        await asyncio.sleep(random.uniform(0.5, 1.2))
        await human_click(page, result)
        await page.wait_for_load_state("domcontentloaded")

        print(f"  Selected test centre: {centre_name}")
        return True
    except Exception as e:
        print(f"  Could not select centre '{centre_name}': {e}")
        return False


# ---------------------------------------------------------------------------
# Step 4b — Postcode search mode
# ---------------------------------------------------------------------------

def _parse_hint_date(text: str) -> Optional[datetime]:
    """Extract DD/MM/YYYY from 'available tests around 23/10/2026', or None."""
    m = re.search(r"(\d{2}/\d{2}/\d{4})", text or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%d/%m/%Y")
    except ValueError:
        return None


async def search_by_postcode(page: Page, postcode: str):
    """Run a postcode search on the test-centre-search page and wait for results."""
    await page.wait_for_selector("body#page-test-centre-search", timeout=15000)
    await asyncio.sleep(random.uniform(1.0, 2.5))
    await move_mouse_naturally(page)

    await page.fill("#test-centres-input", "")
    await human_type(page, "#test-centres-input", postcode)

    submit = page.locator("#test-centres-submit").first
    await move_mouse_naturally(page, locator=submit)
    await asyncio.sleep(random.uniform(0.5, 1.2))
    await human_click(page, submit)
    await page.wait_for_selector("ul.test-centre-results", timeout=15000)
    await asyncio.sleep(random.uniform(0.5, 1.0))


async def read_centre_hints(page: Page, date_from: str, date_to: str, centre_filter=None):
    """
    Parse the postcode search results.  Each centre shows an availability hint:
        <h4>Isleworth (Fleming Way)</h4> <h5>– available tests around 23/10/2026</h5>
    or '– No tests found on any date'.

    Returns [(name, hint_datetime)] for centres worth opening — hint date on or
    before date_to (a hint before date_from can still mean slots in range) —
    sorted earliest first.  centre_filter limits results to listed names.
    """
    d_to = parse_date(date_to)
    promising = []

    items = await page.locator("ul.test-centre-results li").all()
    for li in items:
        link = li.locator("a.test-centre-details-link").first
        try:
            name = (await link.locator("h4").first.text_content() or "").strip()
        except Exception:
            continue
        if not name:
            continue

        try:
            hint_text = (await link.locator("h5").first.text_content() or "").strip()
        except Exception:
            hint_text = ""
        hint_dt = _parse_hint_date(hint_text)

        if hint_dt is None:
            print(f"    {name}: no tests on any date")
            continue

        in_list = (not centre_filter) or any(c.lower() in name.lower() for c in centre_filter)
        if not in_list:
            print(f"    {name}: tests around {hint_dt.strftime('%d/%m/%Y')} (not in centres.yaml — skipped)")
            continue

        if hint_dt <= d_to:
            print(f"    {name}: tests around {hint_dt.strftime('%d/%m/%Y')} → worth checking")
            promising.append((name, hint_dt))
        else:
            print(f"    {name}: tests around {hint_dt.strftime('%d/%m/%Y')} (after {date_to})")

    promising.sort(key=lambda x: x[1])
    return promising


async def open_centre_from_results(page: Page, centre_name: str) -> bool:
    """Click a centre link in the search results and wait for its calendar page."""
    try:
        link = page.locator(f"a.test-centre-details-link:has(h4:text-is('{centre_name}'))").first
        if await link.count() == 0:
            link = page.locator(f"a.test-centre-details-link:has-text('{centre_name}')").first
        await link.wait_for(state="visible", timeout=8000)
        await move_mouse_naturally(page, locator=link)
        await asyncio.sleep(random.uniform(0.5, 1.2))
        await human_click(page, link)
        await page.wait_for_selector("body#page-available-time", timeout=20000)
        return True
    except Exception as e:
        print(f"  Could not open centre '{centre_name}': {e}")
        return False


# ---------------------------------------------------------------------------
# Step 5 — Scan calendar for a slot within date range
# ---------------------------------------------------------------------------

async def scan_for_slot_in_range(
    page: Page,
    date_from: str,
    date_to: str,
    preferred_time: Optional[str] = None,
):
    """
    Two-step booking flow that matches the real DVSA page structure:

      Step 1 — BookingCalendar (always present on page-available-time).
               Reads td.BookingCalendar-date--bookable cells, finds the
               earliest date in the configured range, and clicks its link.

      Step 2 — SlotPicker (loaded/revealed after clicking the calendar date).
               Waits for ul.SlotPicker-days > li#date-YYYY-MM-DD to appear,
               then picks the slot whose time is closest to preferred_time
               (or the earliest slot if no preference is set) and submits.
    """

    # ── Step 1: Read the BookingCalendar ────────────────────────────────────
    try:
        await page.wait_for_selector("table.BookingCalendar-dates", timeout=15000)
    except Exception:
        print("  Booking calendar not found on page")
        return None

    await asyncio.sleep(random.uniform(0.3, 0.7))

    bookable_cells = await page.locator("td.BookingCalendar-date--bookable").all()
    total_bookable = len(bookable_cells)

    # Filter bookable dates to those inside our target range
    candidates = []
    for cell in bookable_cells:
        link = cell.locator("a.BookingCalendar-dateLink").first
        data_date = await link.get_attribute("data-date") or ""
        if date_in_range(data_date, date_from, date_to):
            candidates.append((data_date, link))

    if not candidates:
        if total_bookable:
            # Gather all bookable dates for a useful "nearest available" hint
            all_bookable_dates = []
            for cell in bookable_cells:
                d = await cell.locator("a.BookingCalendar-dateLink").first.get_attribute("data-date") or ""
                if d:
                    all_bookable_dates.append(d)
            all_bookable_dates.sort()
            print(f"  {total_bookable} bookable date(s) — none in range {date_from}–{date_to}")
            if all_bookable_dates:
                print(f"  Nearest available: {all_bookable_dates[0]}")
        else:
            print("  Centre has no bookable dates")
        return None

    # Click the earliest bookable date that falls in our range
    candidates.sort(key=lambda x: x[0])
    earliest_date, date_link = candidates[0]
    print(f"  {len(candidates)} bookable date(s) in range — clicking {earliest_date}")

    await asyncio.sleep(random.uniform(0.5, 1.2))
    await human_click(page, date_link)
    # Allow time for AJAX / reveal animation after clicking the calendar date
    await asyncio.sleep(random.uniform(0.5, 1.0))

    # ── Step 2: Wait for the time-slot list for that specific date ───────────
    slot_li_selector = f"li#date-{earliest_date}"
    try:
        await page.wait_for_selector(slot_li_selector, timeout=12000)
    except Exception:
        # Fallback: accept any day item appearing (different rendering path)
        try:
            await page.wait_for_selector("ul.SlotPicker-days li[id^='date-']", timeout=8000)
        except Exception:
            print(f"  Time slots did not load after clicking {earliest_date}")
            return None

    await asyncio.sleep(random.uniform(0.3, 0.6))

    # ── Step 3: Collect (label, input) pairs for the chosen day ─────────────
    day_item = page.locator(slot_li_selector).first
    labels = await day_item.locator("label.SlotPicker-slot-label").all()
    inputs = await day_item.locator("input.SlotPicker-slot").all()
    slot_pairs = list(zip(labels, inputs))

    if not slot_pairs:
        print(f"  No time slots found for {earliest_date}")
        return None

    print(f"  {len(slot_pairs)} slot(s) available on {earliest_date}")

    # ── Step 4: Pick slot closest to preferred_time (or earliest) ───────────
    pref_mins = _parse_preferred_minutes(preferred_time)
    slot_label, slot_input = slot_pairs[0]   # default: earliest slot

    if pref_mins is not None and len(slot_pairs) > 1:
        best_diff = float("inf")
        for lbl, inp in slot_pairs:
            ts_str = await inp.get_attribute("value") or "0"
            try:
                diff = abs(_slot_minutes(int(ts_str)) - pref_mins)
                if diff < best_diff:
                    best_diff = diff
                    slot_label, slot_input = lbl, inp
            except (ValueError, TypeError):
                pass

    datetime_label = await slot_input.get_attribute("data-datetime-label") or earliest_date
    if pref_mins is not None:
        print(f"  Preferred time {preferred_time} → closest slot: {datetime_label}")
    else:
        print(f"  Booking earliest slot: {datetime_label}")

    # ── Step 5: Click the label (not the raw <input>) and submit ────────────
    # Clicking the <label> fires the JS change event that enables the submit button.
    # Clicking the raw <input> directly does NOT reliably trigger that event.
    await asyncio.sleep(random.uniform(0.5, 1.2))
    await human_click(page, slot_label)

    # Submit starts disabled; DVSA JS enables it once a radio is selected.
    try:
        await page.wait_for_selector("#slot-chosen-submit:not([disabled])", timeout=5000)
    except Exception:
        print("  Warning: submit button did not enable — slot click may not have registered")

    submit = page.locator("#slot-chosen-submit").first
    await submit.wait_for(state="visible", timeout=5000)
    await human_click(page, submit)
    await page.wait_for_load_state("domcontentloaded")

    return datetime_label


# ---------------------------------------------------------------------------
# Step 6 — Change test centre
# ---------------------------------------------------------------------------

async def change_test_centre(page: Page):
    try:
        link = page.locator("a#change-test-centre").first
        await link.wait_for(state="visible", timeout=5000)
        await human_click(page, link)
        await page.wait_for_load_state("domcontentloaded")
        return True
    except Exception as e:
        print(f"  Could not click 'Change test centre': {e}")
        return False


# ---------------------------------------------------------------------------
# Main booking loop
# ---------------------------------------------------------------------------

async def run_booking(
    page: Page,
    date_from: str,
    date_to: str,
    discord_webhook: Optional[str] = None,
    preferred_time: Optional[str] = None,
    search_mode: str = "centres",
    postcode: str = "",
):
    centres = load_centres() or []
    use_postcode = search_mode == "postcode" and bool(postcode)

    if use_postcode:
        print(f"\nPostcode mode: searching '{postcode}' between {date_from} and {date_to}")
        if centres:
            print(f"Centre filter: {', '.join(centres)} (edit centres.yaml to widen)")
        else:
            print("No centre filter — any centre in the results will be considered")
    else:
        print(f"\nSearching {len(centres)} centre(s) between {date_from} and {date_to}")
    if preferred_time:
        print(f"Preferred time: {preferred_time} (bot picks closest slot on the day)")
    print("Retrying every 2.5–5 minutes until a slot is found...\n")

    async def _announce_booking(centre_display, booked_slot):
        print("\n" + "=" * 60)
        print("SLOT BOOKED!")
        print(f"Centre: {centre_display}")
        print(f"Slot:   {booked_slot}")
        print("=" * 60 + "\n")
        if discord_webhook:
            await send_discord_notification(
                discord_webhook,
                {'full_datetime': booked_slot, 'centre': centre_display, 'test_type': 'Car standard'},
                page.url
            )

    if _HUMANIZATION_AVAILABLE:
        print("Mouse emulation: humanization-playwright (Bezier curves)\n")
    else:
        print("Mouse emulation: fallback (random arcs)\n")

    cycle = 0
    challenge_last_cycle = False   # tracks if a challenge fired in the previous cycle

    while True:
        cycle += 1
        print(f"--- Cycle {cycle} ---")

        challenge_this_cycle = False

        async def _captcha_check():
            nonlocal challenge_this_cycle
            was_visible = await _is_captcha_visible(page) or await _is_on_unknown_page(page)
            await wait_for_captcha_clear(page, discord_webhook)
            if was_visible:
                challenge_this_cycle = True

        # ── Postcode mode: one search, availability hints for every centre ──
        if use_postcode:
            await _captcha_check()

            # Get to the search page (first cycle goes through the date form)
            if cycle == 1:
                await fill_test_date(page, date_from)
            else:
                body_id = ""
                try:
                    body_id = await page.locator("body").get_attribute("id") or ""
                except Exception:
                    pass
                if body_id == "page-available-time":
                    await change_test_centre(page)
                elif body_id != "page-test-centre-search":
                    print("  Session may have reset — re-entering date form...")
                    await fill_test_date(page, date_from)

            try:
                await search_by_postcode(page, postcode)
            except Exception as e:
                print(f"  Postcode search failed: {e}")
                await _captcha_check()
            else:
                print("  Availability hints:")
                promising = await read_centre_hints(page, date_from, date_to, centres)

                if not promising:
                    print("  No centre worth opening this cycle.")

                for name, hint_dt in promising:
                    print(f"  Opening {name}...")
                    if not await open_centre_from_results(page, name):
                        await _captcha_check()
                        break
                    await _captcha_check()

                    centre_display = name
                    try:
                        centre_display = (await page.locator("#chosen-test-centre h1").text_content()).strip()
                    except Exception:
                        pass

                    try:
                        booked_slot = await scan_for_slot_in_range(page, date_from, date_to, preferred_time)
                    except Exception as e:
                        print(f"  Scan error: {e}")
                        booked_slot = None

                    if booked_slot:
                        await _announce_booking(centre_display, booked_slot)
                        return True

                    print(f"  No bookable slot in range at {name}.")
                    # Back to the search results for the next promising centre
                    if not await change_test_centre(page):
                        await _captcha_check()
                        break

        # ── Classic mode: open every centre in centres.yaml each cycle ──────
        for i, centre in enumerate([] if use_postcode else centres):
            if i > 0:
                await asyncio.sleep(random.uniform(2, 6))

            print(f"[{i+1}/{len(centres)}] Trying: {centre}")

            # Check for CAPTCHA / challenge before starting each centre
            await _captcha_check()

            if cycle == 1 and i == 0:
                # Very first run: fill the date form then pick centre
                await fill_test_date(page, date_from)
                ok = await select_test_centre(page, centre)

            else:
                # Every subsequent centre: click "Change test centre" to go back
                # to the search page.  If that fails the session has likely reset
                # OR a challenge page is blocking — check before falling back.
                changed = await change_test_centre(page)
                if not changed:
                    # Give the challenge / redirect time to resolve before we
                    # decide it's a session reset and try to re-enter the form.
                    await _captcha_check()

                    # Now figure out where we actually are
                    body_id = ""
                    try:
                        body_id = await page.locator("body").get_attribute("id") or ""
                    except Exception:
                        pass

                    if body_id == "page-available-time":
                        # We're still on the slot page — the "change" link just
                        # wasn't visible yet.  No session reset needed.
                        print("  Still on available-time page — continuing.")
                        ok = True
                    else:
                        print("  Session may have reset — re-entering date form...")
                        await fill_test_date(page, date_from)
                        ok = await select_test_centre(page, centre)
                else:
                    ok = await select_test_centre(page, centre)

            if not ok:
                await _captcha_check()
                continue

            try:
                await page.wait_for_selector("body#page-available-time", timeout=20000)
            except Exception:
                await _captcha_check()
                print(f"  Did not reach available-times page, skipping...")
                continue

            # CAPTCHA can appear on the available-times page too
            await _captcha_check()

            centre_display = centre
            try:
                centre_display = (await page.locator("#chosen-test-centre h1").text_content()).strip()
            except Exception:
                pass

            print(f"  Scanning: {centre_display}")

            try:
                booked_slot = await scan_for_slot_in_range(page, date_from, date_to, preferred_time)
            except Exception as e:
                print(f"  Scan error: {e}")
                booked_slot = None

            if booked_slot:
                await _announce_booking(centre_display, booked_slot)
                return True

            print(f"  No slots at {centre}.\n")

        # ----------------------------------------------------------------
        # Cycle done — wait before the next one.
        #
        # Base wait: 2.5–5 minutes.  Postcode mode keeps each cycle to a
        # single lightweight search, so this cadence stays under the radar
        # while still catching cancellations quickly.
        #
        # If a challenge fired this cycle, add an extra 5–10 minute cooldown
        # first — retrying immediately after a block invites a longer ban.
        #
        # We do NOT reload the page: reloading drops the DVSA wizard session.
        # Instead we scroll gently to keep the session alive.
        # ----------------------------------------------------------------
        challenge_last_cycle = challenge_this_cycle

        if challenge_this_cycle:
            cooldown = random.uniform(300, 600)    # 5–10 min
            print(f"Challenge detected this cycle — cooling down for {cooldown:.0f}s before retrying...\n")
            slices = random.randint(3, 5)
            for _ in range(slices):
                await asyncio.sleep(cooldown / slices)
                await _captcha_check()

        wait_seconds = random.uniform(150, 300)    # 2.5–5 min base
        print(f"Cycle {cycle} done — no slots found. Retrying in {wait_seconds:.0f}s...\n")

        slice_count = random.randint(4, 7)
        for _ in range(slice_count):
            await asyncio.sleep(wait_seconds / slice_count)
            # CAPTCHA can pop up during the idle wait between cycles
            await _captcha_check()
            try:
                h = _make_humanizer(page)
                if h is not None:
                    # Vary the scroll pattern — up, down, pause, back
                    await h.scroll_to(delta_y=random.randint(80, 300))
                    await asyncio.sleep(random.uniform(0.5, 2.0))
                    if random.random() > 0.4:
                        await h.scroll_to(delta_y=-random.randint(40, 150))
                        await asyncio.sleep(random.uniform(0.3, 1.2))
                else:
                    await page.mouse.wheel(0, random.randint(80, 300))
                    await asyncio.sleep(random.uniform(0.5, 2.0))
                    if random.random() > 0.4:
                        await page.mouse.wheel(0, -random.randint(40, 150))
                        await asyncio.sleep(random.uniform(0.3, 1.2))
            except Exception:
                pass
