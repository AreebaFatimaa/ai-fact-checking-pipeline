"""
Fact-Checking Pipeline — Scraper
---------------------------------
Detects the platform from a URL and routes to the right scraper.
Each scraper returns a standardized dict so the rest of the pipeline
doesn't need to know which platform it's dealing with.

Supported platforms:
  - Reddit      → public JSON API (no login, very reliable)
  - YouTube     → yt-dlp + youtube-transcript-api (no login, reliable)
  - X/Twitter   → Playwright browser automation (login required first time)
  - Instagram   → Playwright browser automation (login required first time)
  - Facebook    → Playwright browser automation (login required first time)
"""

import os
import re
import json
import requests
from urllib.parse import urlparse

# Sessions directory: Playwright saves login cookies here so the user
# only needs to log in once per platform.
SESSIONS_DIR = os.path.join(os.path.dirname(__file__), "sessions")
os.makedirs(SESSIONS_DIR, exist_ok=True)

# On Railway (a remote server), there is no screen to show a browser window.
# When ENVIRONMENT=production, browser-based scrapers return a clear message
# instead of crashing. Set this variable in Railway's dashboard.
IS_SERVER = os.environ.get("ENVIRONMENT") == "production"


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

def detect_platform(url: str) -> str:
    """
    Infer the social media platform from a URL.
    Returns one of: "twitter", "reddit", "youtube", "instagram", "facebook", "unknown"
    """
    host = urlparse(url.lower()).netloc.replace("www.", "")

    if host in ("twitter.com", "x.com", "mobile.twitter.com"):
        return "twitter"
    elif "reddit.com" in host:
        return "reddit"
    elif host in ("youtube.com", "youtu.be", "m.youtube.com"):
        return "youtube"
    elif "instagram.com" in host:
        return "instagram"
    elif "facebook.com" in host or host == "fb.com":
        return "facebook"
    else:
        return "unknown"


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

def scrape(url: str) -> dict:
    """
    Main entry point. Detects platform and calls the right scraper.
    Always returns a dict with at minimum: platform, text, image_urls, video_urls, error.
    """
    platform = detect_platform(url)

    if platform == "unknown":
        return _error_result("unknown", f"Unrecognized URL. Supported: X/Twitter, Reddit, YouTube, Instagram, Facebook.")

    scrapers = {
        "reddit":    scrape_reddit,
        "youtube":   scrape_youtube,
        "twitter":   scrape_playwright,
        "instagram": scrape_playwright,
        "facebook":  scrape_playwright,
    }

    if platform in ("twitter", "instagram", "facebook"):
        return scrapers[platform](url, platform)
    else:
        return scrapers[platform](url)


# ---------------------------------------------------------------------------
# Reddit — public JSON API
# ---------------------------------------------------------------------------

def scrape_reddit(url: str) -> dict:
    """
    Reddit exposes a JSON API for any post: just append .json to the URL.
    No login or browser automation needed.
    """
    # Strip query parameters and trailing slashes, then add .json
    clean_url = url.split("?")[0].rstrip("/") + ".json"

    headers = {"User-Agent": "FactCheckPipeline/1.0 (educational journalism tool)"}

    try:
        response = requests.get(clean_url, headers=headers, timeout=15)
        response.raise_for_status()
    except requests.RequestException as e:
        return _error_result("reddit", f"Could not fetch Reddit post: {e}")

    try:
        data = response.json()
        post = data[0]["data"]["children"][0]["data"]
    except (KeyError, IndexError, json.JSONDecodeError):
        return _error_result("reddit", "Could not parse Reddit response — the URL may not point to a specific post.")

    title = post.get("title", "")
    body  = post.get("selftext", "")
    text  = f"{title}\n\n{body}".strip()

    image_urls = []
    video_urls = []

    # If the post links directly to an image
    post_url = post.get("url", "")
    if re.search(r"\.(jpg|jpeg|png|gif|webp)(\?|$)", post_url, re.IGNORECASE):
        image_urls.append(post_url)

    # Reddit-hosted video
    if post.get("is_video"):
        vid_url = post.get("media", {}).get("reddit_video", {}).get("fallback_url")
        if vid_url:
            video_urls.append(vid_url)

    # Preview images from Reddit's CDN (unescape HTML entities)
    for img in post.get("preview", {}).get("images", [])[:2]:
        src = img.get("source", {}).get("url", "").replace("&amp;", "&")
        if src and src not in image_urls:
            image_urls.append(src)

    return {
        "platform":   "reddit",
        "text":       text,
        "author":     post.get("author", ""),
        "image_urls": image_urls,
        "video_urls": video_urls,
        "timestamp":  str(post.get("created_utc", "")),
        "error":      None,
    }


# ---------------------------------------------------------------------------
# YouTube — yt-dlp + transcript API
# ---------------------------------------------------------------------------

def scrape_youtube(url: str) -> dict:
    """
    Uses yt-dlp to get video metadata (title, description, uploader)
    and youtube-transcript-api to get auto-generated captions.
    Works for most public YouTube videos without any login.
    """
    try:
        import yt_dlp
    except ImportError:
        return _error_result("youtube", "yt-dlp not installed. Run: pip install yt-dlp")

    ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        return _error_result("youtube", f"Could not fetch YouTube video info: {e}")

    title       = info.get("title", "")
    description = (info.get("description") or "")[:2000]  # Cap length
    uploader    = info.get("uploader", "")
    video_id    = info.get("id", "")
    thumbnail   = info.get("thumbnail", "")

    text = f"Title: {title}\n\nDescription:\n{description}"

    # Try to get auto-generated captions / transcript
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        segments = YouTubeTranscriptApi.get_transcript(video_id)
        transcript = " ".join(s["text"] for s in segments)[:4000]  # Cap length
        text += f"\n\nVideo transcript:\n{transcript}"
    except Exception:
        text += "\n\n[No captions or transcript available for this video]"

    return {
        "platform":   "youtube",
        "text":       text.strip(),
        "author":     uploader,
        "image_urls": [thumbnail] if thumbnail else [],
        "video_urls": [url],
        "timestamp":  info.get("upload_date", ""),
        "error":      None,
    }


# ---------------------------------------------------------------------------
# Playwright — X/Twitter, Instagram, Facebook
# ---------------------------------------------------------------------------

def scrape_playwright(url: str, platform: str) -> dict:
    """
    Uses Playwright browser automation with a PERSISTENT SESSION.

    First run: a real Chrome window opens. Log in to the platform manually.
               The session (cookies) is saved to sessions/<platform>/.
    Later runs: Chrome opens already logged in — no action needed from the user.

    The browser window closes automatically once content is extracted.
    """
    # On a remote server there is no display — browser automation requires
    # a screen. Direct the user to paste the text manually instead.
    if IS_SERVER:
        return _error_result(
            platform,
            f"Scraping {platform.title()} requires a logged-in browser session, which only works "
            f"in the desktop version of this tool. Please copy and paste the post text manually."
        )

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        return _error_result(platform, "Playwright not installed. Run: pip install playwright && playwright install chromium")

    session_dir = os.path.join(SESSIONS_DIR, platform)

    with sync_playwright() as p:
        # launch_persistent_context saves/restores cookies from session_dir.
        # headless=False means the browser window is visible to the user.
        # The AutomationControlled flag reduces the chance platforms detect us as a bot.
        browser = p.chromium.launch_persistent_context(
            user_data_dir=session_dir,
            headless=False,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )

        page = browser.pages[0] if browser.pages else browser.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            browser.close()
            return _error_result(platform, f"Page failed to load: {e}")

        # Give the page a moment to redirect (e.g. to a login wall)
        page.wait_for_timeout(3000)

        # If we've landed on a login page, wait for the user to log in manually
        if _is_login_page(page.url, platform):
            print(f"\n>>> Please log in to {platform.title()} in the browser window.")
            print(f">>> Waiting up to 90 seconds. The window will close automatically after login.\n")
            try:
                # Poll until the URL no longer looks like a login page
                page.wait_for_function(
                    """() => {
                        const url = window.location.href.toLowerCase();
                        return !url.includes('login') && !url.includes('signin')
                               && !url.includes('accounts') && !url.includes('/auth');
                    }""",
                    timeout=90000,
                )
                page.wait_for_timeout(3000)
                # Navigate to the original URL now that we're logged in
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)
            except Exception:
                browser.close()
                return _error_result(platform, "Login timed out (90 seconds). Please try again.")

        # Extract content using platform-specific logic
        print(f"[scraper] Page loaded. URL: {page.url}")
        try:
            if platform == "twitter":
                result = _extract_twitter(page, url)
            elif platform == "instagram":
                result = _extract_instagram(page, url)
            elif platform == "facebook":
                result = _extract_facebook(page, url)
            else:
                result = {}
        except Exception as e:
            result = {"error": f"Content extraction failed: {e}"}

        print(f"[scraper] Extraction result: text_length={len(result.get('text',''))}, error={result.get('error')}")
        browser.close()

    return {
        "platform":   platform,
        "text":       result.get("text", ""),
        "author":     result.get("author", ""),
        "image_urls": result.get("image_urls", []),
        "video_urls": result.get("video_urls", []),
        "timestamp":  "",
        "error":      result.get("error"),
    }


def _is_login_page(url: str, platform: str) -> bool:
    """Check whether the current URL looks like a login or sign-in page."""
    indicators = ["login", "signin", "sign-in", "accounts/login", "/auth", "session/new"]
    return any(word in url.lower() for word in indicators)


def _extract_twitter(page, url: str) -> dict:
    """Extract text, images, and video flag from a Twitter/X post."""
    from playwright.sync_api import TimeoutError as PWTimeout

    # X often shows a "sign in to continue" modal over public tweets.
    # The modal doesn't change the URL, so we check for it directly and
    # try to close it before extracting content.
    page.wait_for_timeout(2000)
    dismiss_selectors = [
        '[data-testid="sheetDialog"] [aria-label="Close"]',
        '[aria-label="Close"]',
        '[data-testid="app-bar-close"]',
    ]
    for selector in dismiss_selectors:
        btn = page.query_selector(selector)
        if btn:
            try:
                btn.click()
                page.wait_for_timeout(1000)
                break
            except Exception:
                pass

    try:
        page.wait_for_selector('article[data-testid="tweet"]', timeout=15000)
    except PWTimeout:
        return {"error": "Tweet content not found. The post may be deleted, private, or require login."}

    text_el  = page.query_selector('[data-testid="tweetText"]')
    text     = text_el.inner_text() if text_el else ""

    author_el = page.query_selector('[data-testid="User-Name"]')
    author    = author_el.inner_text().split("\n")[0] if author_el else ""

    # Images: Twitter serves images from pbs.twimg.com
    image_urls = []
    for img in page.query_selector_all('[data-testid="tweetPhoto"] img'):
        src = img.get_attribute("src") or ""
        if "pbs.twimg.com" in src:
            # Request the large version instead of the thumbnail
            src = re.sub(r"&name=\w+$", "&name=large", src)
            image_urls.append(src)

    # Video: just note the post URL as the video source for now
    video_urls = []
    if page.query_selector('[data-testid="videoComponent"]'):
        video_urls.append(url)

    return {"text": text, "author": author, "image_urls": image_urls, "video_urls": video_urls}


def _extract_instagram(page, url: str) -> dict:
    """Extract content from an Instagram post using Open Graph meta tags."""
    page.wait_for_timeout(2000)

    # Open Graph tags are the most reliable way to get content from Instagram.
    # These are machine-readable metadata tags in the page's <head>.
    og_desc  = page.query_selector('meta[property="og:description"]')
    og_image = page.query_selector('meta[property="og:image"]')
    og_type  = page.query_selector('meta[property="og:type"]')

    text       = (og_desc.get_attribute("content")  or "") if og_desc  else ""
    image_urls = [(og_image.get_attribute("content") or "")]  if og_image else []
    video_urls = [url] if og_type and "video" in (og_type.get_attribute("content") or "") else []

    return {"text": text, "author": "", "image_urls": image_urls, "video_urls": video_urls}


def _extract_facebook(page, url: str) -> dict:
    """Extract content from a Facebook post using Open Graph meta tags."""
    page.wait_for_timeout(2000)

    og_title = page.query_selector('meta[property="og:title"]')
    og_desc  = page.query_selector('meta[property="og:description"]')
    og_image = page.query_selector('meta[property="og:image"]')
    og_type  = page.query_selector('meta[property="og:type"]')

    title = (og_title.get_attribute("content") or "") if og_title else ""
    desc  = (og_desc.get_attribute("content")  or "") if og_desc  else ""
    text  = f"{title}\n\n{desc}".strip()

    image_urls = [(og_image.get_attribute("content") or "")] if og_image else []
    video_urls = [url] if og_type and "video" in (og_type.get_attribute("content") or "") else []

    return {"text": text, "author": "", "image_urls": image_urls, "video_urls": video_urls}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _error_result(platform: str, message: str) -> dict:
    """Standardized error response."""
    return {
        "platform":   platform,
        "text":       "",
        "author":     "",
        "image_urls": [],
        "video_urls": [],
        "timestamp":  "",
        "error":      message,
    }
