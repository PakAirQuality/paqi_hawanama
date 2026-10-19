"""
Drive the Hawanama dashboard through a scripted tour and capture video + stills.

Prereq: run `python3 scripts/video/login.py` once to save the auth session.

Usage:
    python3 scripts/video/record.py
    python3 scripts/video/record.py --headed      # watch it run
    python3 scripts/video/record.py --slow 1.5    # 1.5x slower pauses

Outputs (in video-output/run_<timestamp>/):
    raw.webm                       Playwright screencast of the full tour
    screenshots/<slug>.png         still at each "chapter"
    manifest.json                  ordered chapter list consumed by stitch.py
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

SITE_URL = "https://hawanama-dashboard.web.app"
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "video-output"
USER_DATA_DIR = OUTPUT_DIR / "user_data_dir"
VIEWPORT = {"width": 1920, "height": 1080}

CHAT_QUESTION = "Which cities have the worst air quality today?"
TIMELINE_TARGET_LABEL = "Nov 6, 2025"  # formatDisplayDate en-US short month
DATE_LABEL_RE = re.compile(r"^[A-Z][a-z]{2} \d{1,2}, \d{4}$")


def wait_for_map(page: Page) -> None:
    page.wait_for_selector("canvas.mapboxgl-canvas", timeout=20000)
    page.wait_for_timeout(2000)


def map_center(page: Page) -> tuple[float, float]:
    box = page.locator("canvas.mapboxgl-canvas").first.bounding_box()
    assert box is not None
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _dispatch_range_value(page: Page, value: int) -> None:
    """Set an input[type=range] value the way React expects.

    React tracks input values via a native setter; assigning .value directly
    doesn't fire onChange. Call the underlying setter and dispatch bubbling
    input+change events so React's synthetic handler picks it up.
    """
    page.evaluate(
        """(v) => {
            const s = document.querySelector('input[type="range"]');
            if (!s) return;
            const setter = Object.getOwnPropertyDescriptor(
                HTMLInputElement.prototype, 'value'
            ).set;
            setter.call(s, String(v));
            s.dispatchEvent(new Event('input', { bubbles: true }));
            s.dispatchEvent(new Event('change', { bubbles: true }));
        }""",
        value,
    )


def scrub_timeline_to(page: Page, target_label: str, slow: float) -> bool:
    """Move the bottom timeline knob so the displayed date equals target_label.

    Uses binary search over the slider's integer index domain. Returns True on
    exact match, False if the closest available date was selected instead.
    """
    slider = page.locator('input[type="range"]').first
    max_attr = slider.get_attribute("max")
    if not max_attr:
        print("   (no timeline slider found)")
        return False
    max_val = int(max_attr)
    if max_val <= 0:
        return False

    # Date label sits inside the timeline bar (.bottom-3), uniquely a centered div.
    label_loc = page.locator('div.absolute.bottom-3 div.text-center').first

    target = datetime.strptime(target_label, "%b %d, %Y").date()

    def cur_date_after(v: int) -> date:
        _dispatch_range_value(page, v)
        page.wait_for_timeout(150)
        txt = label_loc.inner_text().strip()
        return datetime.strptime(txt, "%b %d, %Y").date()

    lo, hi = 0, max_val
    best_v, best_diff = 0, None
    for _ in range(22):
        if lo > hi:
            break
        mid = (lo + hi) // 2
        try:
            cur = cur_date_after(mid)
        except Exception as exc:
            print(f"   (scrub read failed at {mid}: {exc})")
            return False
        diff = (cur - target).days
        if best_diff is None or abs(diff) < abs(best_diff):
            best_v, best_diff = mid, diff
        if diff == 0:
            page.wait_for_timeout(int(3500 * slow))
            return True
        if diff < 0:
            lo = mid + 1
        else:
            hi = mid - 1

    _dispatch_range_value(page, best_v)
    print(f"   (landed {best_diff:+d} days off target)")
    page.wait_for_timeout(int(3500 * slow))
    return False


def scrub_timeline_to_latest(page: Page, slow: float) -> None:
    slider = page.locator('input[type="range"]').first
    max_attr = slider.get_attribute("max")
    if not max_attr:
        return
    _dispatch_range_value(page, int(max_attr))
    page.wait_for_timeout(int(3000 * slow))


def zoom_into_map(page: Page, steps: int, slow: float) -> None:
    cx, cy = map_center(page)
    page.mouse.move(cx, cy)
    for _ in range(steps):
        page.mouse.wheel(0, -250)
        page.wait_for_timeout(int(450 * slow))
    # Let the raster tiles paint at the new zoom before shooting.
    page.wait_for_timeout(int(3500 * slow))


def open_rail_tab(page: Page, title: str) -> None:
    page.locator(f'button[title="{title}"]').first.click()
    page.wait_for_timeout(1000)


def ask_copilot(page: Page, question: str, slow: float) -> None:
    input_box = page.locator('input[placeholder*="Ask about"]').first
    input_box.click()
    input_box.fill("")
    input_box.type(question, delay=35)
    page.wait_for_timeout(int(600 * slow))
    input_box.press("Enter")
    # Wait for the copilot stream; poll the streaming indicator if we can
    page.wait_for_timeout(int(8000 * slow))
    try:
        page.wait_for_function(
            "() => !document.querySelector('button[disabled][type=\"submit\"]')",
            timeout=15000,
        )
    except Exception:
        pass
    page.wait_for_timeout(int(2500 * slow))


def scroll_panel(page: Page, dy: int, reps: int, slow: float) -> None:
    page.mouse.move(250, 540)  # hover over sliding panel
    for _ in range(reps):
        page.mouse.wheel(0, dy)
        page.wait_for_timeout(int(350 * slow))


def click_first_list_button(page: Page) -> bool:
    btn = page.locator('div.overflow-y-auto button').first
    try:
        btn.scroll_into_view_if_needed(timeout=2000)
        btn.click(timeout=3000)
        return True
    except Exception:
        return False


def advance_horizon(page: Page, to_step: int, slow: float) -> None:
    """Advance the forecast horizon by clicking through the dot indicators.

    Dots live inside the top-right horizon pill; each represents Today / D+1 / D+2 / D+3.
    Clicking the last dot directly isn't as cinematic, so step through one at a time.
    """
    dot_selector = ".absolute.top-3.right-3 button.rounded-full"
    dots = page.locator(dot_selector)
    try:
        count = dots.count()
    except Exception:
        count = 0
    if count < 4:
        print(f"   (horizon dots not found — selector matched {count})")
        return
    for i in range(1, to_step + 1):
        try:
            dots.nth(i).click(timeout=3000)
        except Exception as exc:
            print(f"   (horizon step {i} failed: {exc})")
            break
        page.wait_for_timeout(int(2500 * slow))


def shoot(page: Page, screenshots_dir: Path, slug: str, title: str, manifest: list) -> None:
    path = screenshots_dir / f"{slug}.png"
    page.screenshot(path=str(path), full_page=False)
    manifest.append({
        "slug": slug,
        "title": title,
        "screenshot": str(path.name),
    })
    print(f"   [shot] {slug}")


def run_tour(headed: bool, slow: float) -> Path:
    if not USER_DATA_DIR.exists():
        print(f"ERROR: {USER_DATA_DIR} not found.", file=sys.stderr)
        print("Run `python3 scripts/video/login.py` first.", file=sys.stderr)
        sys.exit(1)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / f"run_{timestamp}"
    screenshots_dir = run_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=not headed,
            viewport=VIEWPORT,
            record_video_dir=str(run_dir),
            record_video_size=VIEWPORT,
        )
        page = context.pages[0] if context.pages else context.new_page()

        # ── Chapter 1: Air Quality Tracker ──
        print("-> Air Quality Tracker")
        page.goto(SITE_URL + "/", wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        wait_for_map(page)
        # Prediction raster tiles load after the canvas is ready — give them time.
        page.wait_for_timeout(int(6000 * slow))
        shoot(page, screenshots_dir, "01-tracker", "Air Quality Tracker", manifest)

        print(f"   scrubbing timeline to {TIMELINE_TARGET_LABEL}…")
        scrub_timeline_to(page, TIMELINE_TARGET_LABEL, slow=slow)
        # Raster tiles for historical dates take longer to paint — give them room.
        page.wait_for_timeout(int(5500 * slow))
        shoot(page, screenshots_dir, "02-timeline-nov", f"Historical View — {TIMELINE_TARGET_LABEL}", manifest)

        print("   zooming to reveal stations…")
        zoom_into_map(page, steps=7, slow=slow)
        shoot(page, screenshots_dir, "03-zoomed", "Live Station Network", manifest)

        print("   returning timeline to latest for remaining panels")
        scrub_timeline_to_latest(page, slow=slow)

        # ── Chapter 2: Copilot chat ──
        print("-> Open Copilot chat")
        open_rail_tab(page, "Chat")
        page.wait_for_timeout(int(1200 * slow))
        shoot(page, screenshots_dir, "04-chat-open", "Ask the Copilot", manifest)

        print(f"   asking: {CHAT_QUESTION!r}")
        ask_copilot(page, CHAT_QUESTION, slow=slow)
        shoot(page, screenshots_dir, "05-chat-answer", "Copilot Answers", manifest)

        # ── Chapter 3: Stations panel ──
        print("-> Stations panel")
        open_rail_tab(page, "Stations")
        page.wait_for_timeout(int(1500 * slow))
        shoot(page, screenshots_dir, "06-stations-list", "Monitoring Stations", manifest)

        print("   scrolling list")
        scroll_panel(page, dy=300, reps=4, slow=slow)
        page.wait_for_timeout(int(800 * slow))

        print("   opening first station")
        if click_first_list_button(page):
            page.wait_for_timeout(int(3500 * slow))
            shoot(page, screenshots_dir, "07-station-detail", "Station Detail", manifest)

        # ── Chapter 4: Sources panel ──
        print("-> Sources panel")
        open_rail_tab(page, "Sources")
        page.wait_for_timeout(int(1500 * slow))
        shoot(page, screenshots_dir, "08-sources-list", "Emission Sources", manifest)

        print("   drilling into a source category")
        if click_first_list_button(page):
            page.wait_for_timeout(int(2000 * slow))
            if click_first_list_button(page):
                page.wait_for_timeout(int(3500 * slow))
                shoot(page, screenshots_dir, "09-source-detail", "Source Detail", manifest)

        # ── Chapter 5: Analyst Desk + forecast horizon ──
        print("-> Analyst Desk")
        page.goto(SITE_URL + "/analyst-desk", wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        wait_for_map(page)
        page.wait_for_timeout(int(2500 * slow))
        shoot(page, screenshots_dir, "10-analyst-desk", "Analyst Desk", manifest)

        print("   advancing forecast horizon")
        advance_horizon(page, to_step=3, slow=slow)
        page.wait_for_timeout(int(1500 * slow))
        shoot(page, screenshots_dir, "11-forecast", "3-Day Forecast", manifest)

        video_page = page
        raw_webm_src = Path(video_page.video.path()) if video_page.video else None
        context.close()

    raw_webm_dst = run_dir / "raw.webm"
    if raw_webm_src and raw_webm_src.exists():
        shutil.move(str(raw_webm_src), raw_webm_dst)

    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps({
        "timestamp": timestamp,
        "viewport": VIEWPORT,
        "raw_video": "raw.webm",
        "sections": manifest,
    }, indent=2))

    print(f"\nDone. Artifacts in {run_dir}")
    print("Next: python3 scripts/video/stitch.py " + str(run_dir))
    return run_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--headed", action="store_true", help="show the browser")
    parser.add_argument("--slow", type=float, default=1.0, help="pause multiplier")
    args = parser.parse_args()
    run_tour(args.headed, args.slow)
    return 0


if __name__ == "__main__":
    sys.exit(main())
