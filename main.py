import asyncio
from src.auth import start_now_and_login_with_browser_type
from src.slot_checker import select_car_test, wait_for_test_date_page, run_booking
from config import (
    BROWSER_TYPE, DISCORD_WEBHOOK, DATE_FROM, DATE_TO, PREFERRED_TIME,
    DRIVING_LICENCE_NUMBER, SEARCH_MODE, POSTCODE,
)


async def clear_browser_data(context, page):
    """
    Intentionally left minimal.

    We no longer wipe cookies, cache or storage on exit.  The persistent Chrome
    profile accumulates browsing history and session data over time — exactly
    what Imperva expects from a real user.  Wiping everything at shutdown (or
    startup) creates a "new browser every run" fingerprint that gets flagged.
    """
    pass  # let the profile persist naturally


async def main():
    if not DISCORD_WEBHOOK:
        print("WARNING: DISCORD_WEBHOOK is not set in .env — notifications will be skipped.")

    print(f"Searching for slots between {DATE_FROM} and {DATE_TO}")
    print("Edit DATE_FROM / DATE_TO in config.py to change the range.\n")

    browser, context, page, p = await start_now_and_login_with_browser_type()

    try:
        # Step 1: Bot selects "Car" test type automatically
        await select_car_test(page)

        # Step 2: Bot auto-handles declaration, licence details, info page
        ready = await wait_for_test_date_page(
            page,
            timeout_minutes=10,
            driving_licence=DRIVING_LICENCE_NUMBER,
            discord_webhook=DISCORD_WEBHOOK,
        )
        if not ready:
            print("Did not reach the test date page in time. Exiting.")
            return

        # Step 3: Bot takes over — fills date, selects centres, finds and books a slot
        success = await run_booking(
            page, DATE_FROM, DATE_TO,
            discord_webhook=DISCORD_WEBHOOK,
            preferred_time=PREFERRED_TIME,
            search_mode=SEARCH_MODE,
            postcode=POSTCODE,
        )

        if success:
            print("Slot reserved! Complete your personal details and payment in the browser.")
            input("Press ENTER when you have finished to close the browser...")
        else:
            print("No slots found. Try adjusting your date range or centres in config.py / centres.yaml")

    finally:
        # Always clear browser data on exit regardless of success or error
        await clear_browser_data(context, page)
        await context.close()
        await p.__aexit__(None, None, None)
        print("Session closed and browser data wiped.")


if __name__ == "__main__":
    asyncio.run(main())
