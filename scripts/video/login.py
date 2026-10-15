"""
One-time login helper for the Hawanama dashboard video capture.

Usage:
    python3 scripts/video/login.py

What it does:
    1. Launches a real (headed) Chromium using a persistent user-data directory.
    2. Navigates to the dashboard login page.
    3. Waits for you to finish Google OAuth in the window.
    4. When you hit ENTER, closes cleanly so the session (cookies, localStorage,
       AND IndexedDB — which Firebase Auth uses) stays on disk at
       video-output/user_data_dir/ for record.py to reuse.

The user_data_dir contains auth tokens. It is git-ignored.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SITE_URL = "https://hawanama-dashboard.web.app/"
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "video-output"
USER_DATA_DIR = OUTPUT_DIR / "user_data_dir"


def main() -> int:
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=False,
            viewport={"width": 1920, "height": 1080},
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(SITE_URL, wait_until="domcontentloaded")

        print()
        print("=" * 72)
        print("A Chromium window just opened.")
        print("1. Complete Google sign-in in that window.")
        print("2. Wait until you land on the authenticated dashboard.")
        print("3. Come back here and press ENTER to save the session.")
        print("=" * 72)
        input("Press ENTER when you are logged in > ")

        context.close()
        print(f"\nSession persisted to {USER_DATA_DIR}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
