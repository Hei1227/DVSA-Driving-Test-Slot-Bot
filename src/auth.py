import asyncio
import os
import random
from patchright.async_api import async_playwright
from config import PROFILE_PATH

try:
    from humanization import Humanization, HumanizationConfig
    _HUMANIZATION_AVAILABLE = True
except ImportError:
    _HUMANIZATION_AVAILABLE = False


async def human_wait(min_sec=2, max_sec=5):
    await asyncio.sleep(random.uniform(min_sec, max_sec))


async def clear_startup_data(context, page):
    """
    Wipes cookies, HTTP cache and storage before warm-up browsing.
    Removes fingerprints from previous bot sessions so each run looks fresh.
    """
    print("Clearing previous session data (cookies, cache)...")
    try:
        await context.clear_cookies()
    except Exception:
        pass
    try:
        cdp = await context.new_cdp_session(page)
        await cdp.send("Network.clearBrowserCache")
        await cdp.send("Network.clearBrowserCookies")
        await cdp.detach()
    except Exception:
        pass
    try:
        # Clear any storage that's already accessible on the blank/initial page
        await page.evaluate(
            "() => { try { localStorage.clear(); } catch(e) {} "
            "try { sessionStorage.clear(); } catch(e) {} }"
        )
    except Exception:
        pass
    print("Previous session data cleared.\n")


async def warm_up_browsing(page):
    """
    Visits a random selection of normal UK sites before hitting DVSA to build
    realistic session history that Imperva treats as human.

    Sites are drawn randomly so the sequence is never identical between runs.
    Uses humanization-playwright Bezier-curve mouse movement when available.
    """
    # Large pool — bot picks 3-5 at random so no two runs look the same
    _WARM_UP_POOL = [
        "https://www.google.co.uk",
        "https://www.bbc.co.uk",
        "https://www.gov.uk",
        "https://www.autotrader.co.uk",
        "https://www.rightmove.co.uk",
        "https://www.theguardian.com",
        "https://www.amazon.co.uk",
        "https://www.bbc.co.uk/news",
        "https://www.skysports.com",
        "https://www.met.gov.uk",
        "https://www.nhs.uk",
        "https://www.ebay.co.uk",
        "https://www.tripadvisor.co.uk",
        "https://www.zoopla.co.uk",
        "https://www.asos.com"
    ]
    warm_up_sites = random.sample(_WARM_UP_POOL, k=random.randint(3, 5))

    print("Warming up browser with human-like activity...")

    # Build humanizer once we have a page
    h = None
    if _HUMANIZATION_AVAILABLE:
        config = HumanizationConfig(humanize=True, stealth_mode=True)
        h = Humanization(page, config)
        print("  Mouse emulation: humanization-playwright (Bezier curves)")
    else:
        print("  Mouse emulation: fallback (random arcs)")

    for url in warm_up_sites:
        try:
            await page.goto(url)
            await page.wait_for_load_state("domcontentloaded")

            if h is not None:
                # Smooth scroll with inertia
                for _ in range(random.randint(2, 4)):
                    await h.scroll_to(delta_y=random.randint(200, 500))
                    await asyncio.sleep(random.uniform(0.5, 1.2))
                # Move mouse to a few random body positions using Bezier arcs
                for _ in range(random.randint(2, 4)):
                    body = page.locator("body").first
                    await h.move_to(body, offset_x=random.randint(-200, 200), offset_y=random.randint(-100, 100))
                    await asyncio.sleep(random.uniform(0.3, 0.8))
            else:
                for _ in range(random.randint(2, 4)):
                    await page.mouse.wheel(0, random.randint(200, 500))
                    await asyncio.sleep(random.uniform(0.5, 1.2))
                for _ in range(random.randint(3, 6)):
                    x = random.randint(200, 900)
                    y = random.randint(150, 550)
                    await page.mouse.move(x, y, steps=random.randint(8, 20))
                    await asyncio.sleep(random.uniform(0.2, 0.6))

            await asyncio.sleep(random.uniform(3, 7))

        except Exception:
            pass

    print("Warm-up done.")


async def handle_already_signed_in_page(page):
    try:
        already_signed_in = await page.locator("h1:has-text('You are already signed in')").count()
        if already_signed_in > 0:
            print("Handling 'You are already signed in' page...")
            await page.click("input#confirm-Stay")
            await page.click("button#continue")
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(2)
            return True
        return False
    except Exception as e:
        print(f"Error handling signed in page: {e}")
        return False


async def start_now_and_login_with_browser_type(browser_type="chrome"):
    """
    Launches a patchright persistent context using the bot Chrome profile.
    Patchright patches Chromium at the binary level — no JS-layer stealth
    patches that Imperva can fingerprint.
    """
    print("Launching browser with patchright (undetected mode)...")

    os.makedirs(PROFILE_PATH, exist_ok=True)

    p = await async_playwright().__aenter__()

    # launch_persistent_context keeps cookies/history between runs
    # and is the recommended patchright approach for avoiding detection
    context = await p.chromium.launch_persistent_context(
        user_data_dir=PROFILE_PATH,
        headless=False,
        no_viewport=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--start-maximized",
        ],
    )

    page = context.pages[0] if context.pages else await context.new_page()

    # NOTE: We deliberately do NOT clear cookies or cache here.
    # The persistent Chrome profile is the primary defence against Imperva
    # detection.  Wiping everything at startup creates a "fresh browser"
    # fingerprint on every run — that pattern is MORE suspicious, not less.
    # A profile that has accumulated real browsing history over time looks human.

    # Warm up with normal browsing before hitting DVSA
    await warm_up_browsing(page)

    # Navigate to the DVSA booking site
    print("Navigating to the DVSA booking site...")
    await page.goto("https://driverpracticaltest.dvsa.gov.uk/application?execution=e2s1")
    await page.wait_for_load_state("domcontentloaded")

    await asyncio.sleep(random.uniform(1, 3))

    # If redirected to login, wait up to 3 minutes for manual sign-in
    if "login" in page.url.lower() or "signin" in page.url.lower():
        print("Please sign in manually in the browser. Waiting up to 3 minutes...")
        try:
            await page.wait_for_url("**/application**", timeout=180000)
        except Exception:
            print("Timed out waiting for sign-in. Please restart the bot after signing in.")
            raise

    await handle_already_signed_in_page(page)

    # Wait up to 90 s for any DVSA page to appear.
    # Imperva/Incapsula challenges can hold the page for 30-60 s — this gives
    # the user time to solve them manually if the auto-pass fails.
    print("Waiting for DVSA booking page (may pause if a verification challenge appears)...")
    try:
        await page.wait_for_selector("form, body[id^='page-']", timeout=90000)
        print("DVSA page loaded — bot is standing by.")
    except Exception:
        print(
            "Note: DVSA page did not confirm load within 90 s.\n"
            "If a verification challenge is showing, please solve it in the browser.\n"
            "The bot will continue watching and pick up once the page loads."
        )

    # Return context as "browser" so main.py cleanup still works
    return context, context, page, p
