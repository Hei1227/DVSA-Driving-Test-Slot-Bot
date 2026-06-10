import aiohttp


async def send_captcha_alert(webhook_url: str):
    """Send a Discord ping telling the user a CAPTCHA needs solving."""
    if not webhook_url:
        return False
    payload = {
        "content": (
            "⚠️ **CAPTCHA DETECTED**\n"
            "The DVSA site is showing a human verification challenge.\n"
            "Please open the browser and solve it — the bot will resume automatically once it's cleared."
        )
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload) as response:
                return response.status == 204
    except Exception as e:
        print(f"Discord captcha alert error: {e}")
        return False


async def send_discord_notification(webhook_url: str, booking_details: dict, page_url: str = None):
    if not webhook_url:
        return False

    message = (
        f"{booking_details.get('full_datetime', 'Unknown')}\t"
        f"{booking_details.get('test_type', 'Car standard')}\t"
        f"{booking_details.get('centre', 'Unknown')}\t"
        f"£62.00"
    )

    payload = {"content": f"**BOOKING CONFIRMED**\n```{message}```"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload) as response:
                return response.status == 204
    except Exception as e:
        print(f"Discord notification error: {e}")
        return False
