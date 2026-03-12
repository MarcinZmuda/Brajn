"""
Page scraper with Cloudflare Browser Rendering as default,
fallback to requests+trafilatura.

Cloudflare Browser Rendering API:
https://developers.cloudflare.com/browser-rendering/
"""
import re
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.common.config import (
    CF_BROWSER_RENDERING_URL,
    CF_BROWSER_RENDERING_TOKEN,
    MAX_CONTENT_SIZE,
    MAX_TOTAL_CONTENT,
    SCRAPE_TIMEOUT,
    SKIP_DOMAINS,
)

try:
    import trafilatura
    TRAFILATURA_AVAILABLE = True
except ImportError:
    TRAFILATURA_AVAILABLE = False

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def should_skip_url(url: str) -> bool:
    """Check if URL should be skipped (large docs, PDFs, etc.)."""
    url_lower = url.lower()
    for pattern in SKIP_DOMAINS:
        if pattern in url_lower:
            return True
    if any(url_lower.endswith(ext) for ext in [".pdf", ".doc", ".docx", ".xls", ".xlsx"]):
        return True
    return False


def _scrape_cf_browser_rendering(url: str, timeout: int = SCRAPE_TIMEOUT) -> str | None:
    """
    Scrape page using Cloudflare Browser Rendering API.
    Returns raw HTML or None on failure.

    Uses the /content endpoint which returns rendered HTML.
    See: https://developers.cloudflare.com/browser-rendering/rest-api/content/
    """
    if not CF_BROWSER_RENDERING_URL:
        return None

    try:
        headers = {"Content-Type": "application/json"}
        if CF_BROWSER_RENDERING_TOKEN:
            headers["Authorization"] = f"Bearer {CF_BROWSER_RENDERING_TOKEN}"

        response = requests.post(
            f"{CF_BROWSER_RENDERING_URL}/content",
            json={
                "url": url,
                "waitUntil": "networkidle0",
                "rejectResourceTypes": ["image", "font", "media"],
                "bestAttempt": True,
            },
            headers=headers,
            timeout=timeout + 5,
        )

        if response.status_code == 200:
            data = response.json() if response.headers.get("content-type", "").startswith("application/json") else None
            if data:
                return data.get("html", data.get("content", ""))
            return response.text

        print(f"[SCRAPER] CF Browser Rendering HTTP {response.status_code} for {url[:50]}")
        return None

    except Exception as e:
        print(f"[SCRAPER] CF Browser Rendering error for {url[:50]}: {e}")
        return None


def _scrape_requests_fallback(url: str, timeout: int = SCRAPE_TIMEOUT) -> str | None:
    """Scrape page using simple requests + smart encoding."""
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT},
        )
        if response.status_code != 200:
            return None

        content_type = response.headers.get("Content-Type", "")
        if "charset=" in content_type.lower():
            return response.text
        try:
            return response.content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                return response.content.decode("windows-1250")
            except UnicodeDecodeError:
                return response.content.decode("utf-8", errors="replace")

    except requests.exceptions.Timeout:
        print(f"[SCRAPER] Timeout for {url[:50]} (>{timeout}s)")
        return None
    except Exception as e:
        print(f"[SCRAPER] Request error for {url[:50]}: {e}")
        return None


def _extract_h2_from_html(html: str) -> list[str]:
    """Extract clean H2 headings from HTML."""
    html_for_h2 = html[:MAX_CONTENT_SIZE * 4]
    h2_tags = re.findall(r"<h2[^>]*>(.*?)</h2>", html_for_h2, re.IGNORECASE | re.DOTALL)
    h2_clean = [re.sub(r"<[^>]+>", "", h).strip() for h in h2_tags]
    return [
        h for h in h2_clean
        if h and len(h) < 200 and not re.search(r"[{};]|webkit|moz-|flex-|align-items", h, re.IGNORECASE)
    ]


def _extract_content_from_html(html: str) -> str | None:
    """Extract clean text content from HTML using trafilatura or regex fallback."""
    content = None

    if TRAFILATURA_AVAILABLE:
        try:
            content = trafilatura.extract(
                html[:500_000],
                include_comments=False,
                include_tables=True,
                no_fallback=False,
                favor_precision=False,
            )
        except Exception as e:
            print(f"[SCRAPER] trafilatura failed: {e}")
            content = None

    if not content:
        raw = html
        if len(raw) > MAX_CONTENT_SIZE * 2:
            raw = raw[: MAX_CONTENT_SIZE * 2]
        raw = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL | re.IGNORECASE)
        raw = re.sub(r"<style[^>]*>.*?</style>", "", raw, flags=re.DOTALL | re.IGNORECASE)
        raw = re.sub(r"<nav[^>]*>.*?</nav>", "", raw, flags=re.DOTALL | re.IGNORECASE)
        raw = re.sub(r"<footer[^>]*>.*?</footer>", "", raw, flags=re.DOTALL | re.IGNORECASE)
        raw = re.sub(r"<header[^>]*>.*?</header>", "", raw, flags=re.DOTALL | re.IGNORECASE)
        raw = re.sub(r"<[^>]+>", " ", raw)
        content = re.sub(r"\s+", " ", raw).strip()

    if not content:
        return None

    # Apply data_cleaner for deeper boilerplate removal
    try:
        from src.s1.data_cleaner import clean_scraped_content
        content = clean_scraped_content(content, max_chars=MAX_CONTENT_SIZE)
    except ImportError:
        content = content[:MAX_CONTENT_SIZE]

    return content if content else None


def scrape_one(url: str, title: str = "") -> dict | None:
    """
    Scrape a single URL. Tries Cloudflare Browser Rendering first, then fallback.
    Returns source dict or None.
    """
    if should_skip_url(url):
        print(f"[SCRAPER] Skipping: {url[:60]}")
        return None

    t0 = time.time()

    # Try Cloudflare Browser Rendering first
    raw_html = _scrape_cf_browser_rendering(url)
    scrape_method = "cloudflare"

    # Fallback to requests
    if not raw_html:
        raw_html = _scrape_requests_fallback(url)
        scrape_method = "requests"

    if not raw_html:
        return None

    h2_clean = _extract_h2_from_html(raw_html)
    content = _extract_content_from_html(raw_html)

    if not content or len(content) < 500:
        print(f"[SCRAPER] Too short content from {url[:50]}")
        return None

    elapsed = time.time() - t0
    word_count = len(content.split())
    print(f"[SCRAPER] {scrape_method}: {len(content)} chars, {word_count} words, {len(h2_clean)} H2 from {url[:50]} [{elapsed:.1f}s]")

    return {
        "url": url,
        "title": title,
        "content": content,
        "h2_structure": h2_clean[:15],
        "word_count": word_count,
        "scrape_method": scrape_method,
    }


def scrape_parallel(targets: list[dict], max_workers: int = 6) -> list[dict]:
    """
    Scrape multiple URLs in parallel.
    targets: list of {"url": ..., "title": ...}
    Returns list of successful source dicts.
    """
    t_start = time.time()
    print(f"[SCRAPER] Parallel scraping {len(targets)} pages...")

    sources = []
    total_content_size = 0

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(scrape_one, t.get("url", ""), t.get("title", "")): t
            for t in targets
            if t.get("url")
        }
        for future in as_completed(futures):
            result = future.result()
            if result and total_content_size < MAX_TOTAL_CONTENT:
                sources.append(result)
                total_content_size += len(result["content"])

    elapsed = time.time() - t_start
    print(f"[SCRAPER] Done: {len(sources)} sources ({total_content_size} chars) in {elapsed:.1f}s")
    return sources
