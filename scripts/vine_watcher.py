"""
scripts/vine_watcher.py
Automated Amazon Vine Potluck (RFY) monitor for Sarahzine 800.
Monitors https://www.amazon.com/vine/vine-items?queue=potluck
Captures screenshots and sends direct product links to Telegram.
"""

import os
import sys
import time
import logging
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Ensure console handles UTF-8 on Windows cp1252
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure ChipAI root is on sys.path so we can import telegram_service and assistant
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

load_dotenv(BASE_DIR / ".env")

import telegram_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("chipai.vine_watcher")

# Local AppData profile path prevents Google Drive sync file locks
DEFAULT_PROFILE_DIR = Path(os.path.expanduser(r"~/.gemini/vine_profile"))
PROFILE_DIR = Path(os.getenv("VINE_PROFILE_DIR", str(DEFAULT_PROFILE_DIR)))

VINE_POTLUCK_URL = "https://www.amazon.com/vine/vine-items?queue=potluck"
TARGET_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "5127043704")


def interactive_login():
    """Launch standard Google Chrome with the dedicated profile so Chip can log in."""
    from playwright.sync_api import sync_playwright

    print("=" * 65)
    print("[*] SARAHZINE 800 - AMAZON VINE AUTHENTICATION SETUP")
    print("=" * 65)
    print(f"Profile location: {PROFILE_DIR}")
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    print("\nLaunching browser window...")
    print("1. Log in to your Amazon account in the opened window.")
    print("2. Check 'Keep me signed in' if prompted.")
    print("3. Complete 2FA and ensure your Vine Potluck queue appears.")
    print("4. Once you are in Vine Potluck, the window will auto-detect and save (or you can close it).")
    print("=" * 65 + "\n")

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                channel="chrome",
                headless=False,
                viewport={"width": 1440, "height": 900},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(VINE_POTLUCK_URL)

            print("[*] Waiting for login completion...")
            while len(context.pages) > 0 and not page.is_closed():
                time.sleep(1.5)
                try:
                    cur_url = page.url.lower()
                    if "vine-items?queue=potluck" in cur_url:
                        if page.query_selector("#vvp-items-grid") or page.query_selector(".vvp-tab-content"):
                            print("\n[+] Vine Potluck detected and active! Saving session...")
                            time.sleep(2)
                            break
                except Exception:
                    break

            try:
                context.close()
            except Exception:
                pass
            print("\n[+] Browser closed! Amazon session and cookies saved successfully.")
    except Exception as e:
        print(f"[!] Error launching login browser: {e}")



def check_and_capture_potluck(notify_telegram: bool = True, custom_caption_prefix: str = "") -> dict:
    """Headlessly check Vine Potluck, capture screenshot, and dispatch to Telegram.
    Returns dict with summary: {'status': 'success'|'empty'|'expired'|'error', 'items': [...], 'screenshot_bytes': ...}
    """
    from playwright.sync_api import sync_playwright

    if not PROFILE_DIR.exists():
        err = f"Profile directory not found at {PROFILE_DIR}. Please run 'python scripts/vine_watcher.py login' first."
        logger.error(err)
        if notify_telegram:
            telegram_service.send_message(
                TARGET_CHAT_ID,
                "⚠️ Hey Chip, Amazon Vine monitor isn't set up yet! Run `python scripts/vine_watcher.py login` once on your machine to save your login session."
            )
        return {"status": "not_configured", "error": err}

    logger.info("Starting headless Chrome to check Amazon Vine Potluck queue...")
    screenshot_bytes = None
    items = []

    try:
        with sync_playwright() as p:
            try:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(PROFILE_DIR),
                    channel="chrome",
                    headless=True,
                    viewport={"width": 1440, "height": 1000},
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                    ],
                )
            except Exception as launch_err:
                logger.info(f"Falling back to default Chromium: {launch_err}")
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(PROFILE_DIR),
                    headless=True,
                    viewport={"width": 1440, "height": 1000},
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                    ],
                )
            page = context.pages[0] if context.pages else context.new_page()
            
            # Go to Potluck queue
            logger.info(f"Navigating to {VINE_POTLUCK_URL}")
            page.goto(VINE_POTLUCK_URL, wait_until="domcontentloaded", timeout=45000)
            time.sleep(4)

            # Check if redirected to sign-in or session expired
            current_url = page.url.lower()
            if ("signin" in current_url or "ap/signin" in current_url) and "queue=potluck" not in current_url:
                logger.warning("Amazon Vine session expired or redirected to sign-in page!")
                if notify_telegram:
                    telegram_service.send_message(
                        TARGET_CHAT_ID,
                        "⚠️ **Sarahzine Vine Alert**: Hey Chip, my Amazon Vine session has expired! Please run option 2 to re-authenticate."
                    )
                context.close()
                return {"status": "expired"}

            # Check for bot challenge / captcha
            page_content = page.content().lower()
            if "captcha" in page_content or "enter the characters you see below" in page_content:
                logger.warning("Amazon displayed a bot challenge / captcha.")
                if notify_telegram:
                    telegram_service.send_message(
                        TARGET_CHAT_ID,
                        "🤖 **Sarahzine Alert**: Amazon showed a CAPTCHA challenge on Vine. Running `python scripts/vine_watcher.py login` once will clear it."
                    )
                context.close()
                return {"status": "captcha"}

            # Wait for items grid or empty queue text
            logger.info("Looking for Vine items...")
            time.sleep(2)

            grid = page.query_selector("#vvp-items-grid")
            if not grid:
                grid = page.query_selector(".vvp-tab-content")

            # Extract item tiles
            tiles = page.query_selector_all(".vvp-item-tile")
            logger.info(f"Found {len(tiles)} item tile(s) in Potluck queue.")

            for tile in tiles:
                try:
                    title_elem = tile.query_selector(".a-link-normal") or tile.query_selector(".vvp-item-tile-title")
                    title = title_elem.inner_text().strip() if title_elem else "Vine Product"
                    href = title_elem.get_attribute("href") if title_elem else ""
                    if href and href.startswith("/"):
                        href = f"https://www.amazon.com{href}"
                    
                    # Try to extract ASIN or clean Amazon URL
                    asin = tile.get_attribute("data-asin") or ""
                    clean_url = f"https://www.amazon.com/dp/{asin}" if asin else href

                    items.append({
                        "title": title,
                        "url": clean_url or VINE_POTLUCK_URL,
                        "asin": asin,
                    })
                except Exception as ex:
                    logger.debug(f"Error parsing tile: {ex}")

            # Capture screenshot
            # If grid is visible and has height, screenshot the grid specifically; otherwise screenshot viewport
            if grid:
                try:
                    screenshot_bytes = grid.screenshot()
                except Exception:
                    screenshot_bytes = page.screenshot(full_page=False)
            else:
                screenshot_bytes = page.screenshot(full_page=False)

            # Save local copy for reference / debugging
            data_dir = BASE_DIR / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            last_shot_path = data_dir / "vine_last_potluck.png"
            with open(last_shot_path, "wb") as f:
                f.write(screenshot_bytes)
            logger.info(f"Saved local screenshot to {last_shot_path}")

            context.close()

    except Exception as e:
        logger.error(f"Error during Vine Potluck capture: {e}", exc_info=True)
        if notify_telegram:
            telegram_service.send_message(
                TARGET_CHAT_ID,
                f"❌ Hey Chip, error checking Amazon Vine: {str(e)[:150]}"
            )
        return {"status": "error", "error": str(e)}

    # Send screenshot and formatted message to Telegram
    if notify_telegram and screenshot_bytes:
        now_str = datetime.now().strftime("%I:%M %p").lstrip("0")
        
        prefix = custom_caption_prefix or f"🌿 **Sarahzine 800 • Vine Potluck ({now_str})**\n\n"
        caption = prefix
        caption += f"Here are your Recommended For You items! (You have **3 picks** available today):\n\n"

        if items:
            for idx, it in enumerate(items[:6], 1):
                clean_title = (it["title"][:50] + "...") if len(it["title"]) > 50 else it["title"]
                caption += f"{idx}. [{clean_title}]({it['url']})\n"
        else:
            caption += "ℹ️ *Your Potluck queue currently has 0 items right now.*\n"

        caption += f"\n🔗 [Open Amazon Vine Potluck]({VINE_POTLUCK_URL})"

        sent = telegram_service.send_photo(TARGET_CHAT_ID, screenshot_bytes, caption=caption)
        if sent:
            logger.info(f"Dispatched Vine Potluck photo and {len(items)} items to Telegram {TARGET_CHAT_ID}")
        else:
            logger.warning("Failed to send photo via Telegram Bot API, sending text fallback.")
            telegram_service.send_message(TARGET_CHAT_ID, caption)

    return {
        "status": "success",
        "items": items,
        "screenshot_bytes": screenshot_bytes,
    }


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].lower() in ["login", "--login", "-l", "auth"]:
        interactive_login()
    else:
        # Check and send
        result = check_and_capture_potluck(notify_telegram=True)
        print(f"\nExecution finished: status={result.get('status')}, items_count={len(result.get('items', []))}")
