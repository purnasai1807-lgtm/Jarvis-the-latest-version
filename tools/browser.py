"""
Browser automation tools (Phase 3) — Playwright + DuckDuckGo + BeautifulSoup.

Persistent browser: stays open between commands for speed.
web_search uses DuckDuckGo (no API key needed).
summarize_article and summarize_youtube return raw content; Claude synthesizes.
"""

import re
import textwrap
from loguru import logger

# ── Persistent Playwright state ───────────────────────────────────
_playwright = None
_browser = None
_page = None

_MAX_CONTENT = 8000   # chars sent back to Claude


def _get_active_tab_url() -> str:
    """Grab the URL from the active Chrome tab via Windows UI Automation.
    Uses PowerShell to read Chrome's address bar — no focus stealing, no blocking."""
    import subprocess

    ps_script = r"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$chrome = [System.Diagnostics.Process]::GetProcessesByName('chrome') |
          Where-Object { $_.MainWindowHandle -ne 0 } |
          Select-Object -First 1
if (-not $chrome) { Write-Error 'No Chrome window'; exit 1 }
$root = [System.Windows.Automation.AutomationElement]::FromHandle($chrome.MainWindowHandle)
$cond = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Edit)
$edits = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
foreach ($e in $edits) {
    $name = $e.Current.Name
    if ($name -match 'Address|Search|search') {
        $vp = $e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
        Write-Output $vp.Current.Value
        exit 0
    }
}
Write-Error 'Address bar not found'; exit 1
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        capture_output=True, text=True, timeout=8,
    )
    url = result.stdout.strip()
    if not url:
        raise RuntimeError(
            f"Could not read Chrome URL via UI Automation "
            f"(stderr: {result.stderr.strip()[:200]})"
        )
    # Chrome address bar omits the scheme — add it back if needed
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    logger.info(f"Active tab URL: {url}")
    return url


def _get_page():
    """Return the persistent browser page, launching if needed."""
    global _playwright, _browser, _page

    if _page is not None and not _page.is_closed():
        return _page

    from playwright.sync_api import sync_playwright

    if _playwright is None:
        _playwright = sync_playwright().start()

    if _browser is None or not _browser.is_connected():
        _browser = _playwright.chromium.launch(
            headless=True,          # invisible — no ghost Chrome window
        )

    context = _browser.new_context(no_viewport=True)
    _page = context.new_page()
    logger.info("Browser launched (Chromium)")
    return _page


def _clean_text(raw: str) -> str:
    """Collapse blank lines and trim to _MAX_CONTENT chars."""
    text = re.sub(r'\n{3,}', '\n\n', raw.strip())
    return textwrap.shorten(text, width=_MAX_CONTENT, placeholder=" … [truncated]")


# ── Handlers ─────────────────────────────────────────────────────

def web_search(query: str) -> str:
    """Search the web via DuckDuckGo and return the top results."""
    try:
        from ddgs import DDGS

        results = list(DDGS().text(query, max_results=6))
        if not results:
            return f"No results found for: {query}"

        lines = [f"Search results for: {query}\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}\n   {r['body']}\n   {r['href']}")

        logger.info(f"web_search({query!r}): {len(results)} results")
        return "\n\n".join(lines)

    except Exception as exc:
        logger.error(f"web_search failed: {exc}")
        return f"Search failed: {exc}"


def get_weather(city: str, days: int = 1) -> str:
    """Fetch weather for a city using wttr.in and return a human-readable summary."""
    try:
        import requests, json

        url = f"https://wttr.in/{city}?format=j1"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "curl/7.68.0"})
        resp.raise_for_status()
        data = resp.json()

        lines = []

        # Current conditions
        cur = data["current_condition"][0]
        desc = cur["weatherDesc"][0]["value"]
        temp_c = cur["temp_C"]
        feels_c = cur["FeelsLikeC"]
        humidity = cur["humidity"]
        wind_kmph = cur["windspeedKmph"]
        lines.append(
            f"Current in {city}: {desc}, {temp_c}°C (feels like {feels_c}°C), "
            f"humidity {humidity}%, wind {wind_kmph} km/h."
        )

        # Forecast for requested days
        weather_days = data.get("weather", [])
        for i, day in enumerate(weather_days[:max(days, 1)]):
            date = day["date"]
            max_c = day["maxtempC"]
            min_c = day["mintempC"]
            desc_day = day["hourly"][4]["weatherDesc"][0]["value"]  # noon forecast
            rain_mm = day["hourly"][4].get("precipMM", "0")
            label = "Today" if i == 0 else ("Tomorrow" if i == 1 else f"In {i} days")
            lines.append(
                f"{label} ({date}): {desc_day}, high {max_c}°C / low {min_c}°C, "
                f"precipitation {rain_mm} mm."
            )

        result = " ".join(lines)
        logger.info(f"get_weather({city}): {result[:120]}")
        return result

    except Exception as exc:
        logger.error(f"get_weather failed: {exc}")
        return f"Could not get weather for {city}: {exc}"


def read_page(url: str = None) -> str:
    """Extract readable text from a URL or the currently open browser page."""
    try:
        page = _get_page()

        if url:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(1000)  # let JS settle

        text = page.evaluate("""() => {
            const doc = document.cloneNode(true);
            for (const tag of ['script','style','nav','footer','header','aside','iframe']) {
                doc.querySelectorAll(tag).forEach(el => el.remove());
            }
            return doc.body?.innerText ?? '';
        }""")

        result = _clean_text(text)
        logger.info(f"read_page({url or 'current'}): {len(result)} chars")
        return result or "Page appears to be empty or unreadable."

    except Exception as exc:
        logger.error(f"read_page failed: {exc}")
        return f"Failed to read page: {exc}"


def fill_form(fields: dict) -> str:
    """Fill form fields on the current browser page.
    fields: mapping of CSS selector → value (e.g. {'#email': 'me@example.com'})."""
    try:
        page = _get_page()
        filled = []
        for selector, value in fields.items():
            page.fill(selector, str(value))
            filled.append(selector)
        logger.info(f"fill_form: filled {filled}")
        return f"Filled {len(filled)} field(s): {', '.join(filled)}"
    except Exception as exc:
        logger.error(f"fill_form failed: {exc}")
        return f"Failed to fill form: {exc}"


def click_element(description: str) -> str:
    """Click a page element identified by visible text or CSS selector."""
    try:
        page = _get_page()
        # Try visible text first, then treat as CSS selector
        try:
            page.click(f"text={description}", timeout=5000)
        except Exception:
            page.click(description, timeout=5000)
        logger.info(f"click_element: clicked '{description}'")
        return f"Clicked '{description}'."
    except Exception as exc:
        logger.error(f"click_element failed: {exc}")
        return f"Could not click '{description}': {exc}"


def summarize_article(url: str = None) -> str:
    """Fetch a web article and return its text content for summarization."""
    try:
        import requests
        from bs4 import BeautifulSoup

        if not url:
            url = _get_active_tab_url()
        elif not url.startswith(("http://", "https://")):
            url = "https://" + url

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            )
        }
        resp = requests.get(url, headers=headers, timeout=12)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        result = _clean_text(text)
        logger.info(f"summarize_article({url}): {len(result)} chars")
        return result or "Could not extract article text."

    except Exception as exc:
        logger.error(f"summarize_article failed: {exc}")
        return f"Failed to fetch article: {exc}"


def summarize_youtube(url: str = None) -> str:
    """Get a YouTube video's transcript for summarization."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        if not url:
            url = _get_active_tab_url()

        # Extract video ID from various YouTube URL formats
        match = re.search(r"(?:v=|youtu\.be/|/embed/)([A-Za-z0-9_-]{11})", url)
        if not match:
            return "Could not extract a YouTube video ID from that URL."

        video_id = match.group(1)
        # Try English first, fall back to any available language
        try:
            entries = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "ro"])
        except Exception:
            transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
            entries = next(iter(transcripts)).fetch()

        text = " ".join(e["text"] for e in entries)
        result = _clean_text(text)
        logger.info(f"summarize_youtube({video_id}): {len(result)} chars")
        return result or "Transcript appears to be empty."

    except Exception as exc:
        logger.error(f"summarize_youtube failed: {exc}")
        return f"Could not get YouTube transcript: {exc}"


def close_browser() -> str:
    """Close the browser window."""
    global _browser, _page, _playwright
    try:
        if _page and not _page.is_closed():
            _page.close()
        if _browser and _browser.is_connected():
            _browser.close()
        if _playwright:
            _playwright.stop()
        _page = _browser = _playwright = None
        logger.info("Browser closed")
        return "Browser closed."
    except Exception as exc:
        return f"Error closing browser: {exc}"


# ── Tool definitions ─────────────────────────────────────────────

TOOLS = [
    {
        "name": "web_search",
        "description": (
            "Search the web using DuckDuckGo and return the top results with titles, "
            "snippets, and URLs. Use this to find information, news, prices, or anything "
            "that requires looking things up online. Do NOT open a browser for this — "
            "it works without one."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g. 'cheap flights Bucharest London June 2026')",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_weather",
        "description": (
            "Get the current weather and forecast for a city. "
            "Use this for any weather question — current conditions or forecast for today/tomorrow/next few days. "
            "Returns a human-readable summary with temperature, description, humidity, wind, and precipitation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City name (e.g. 'Bucharest', 'London', 'New York')",
                },
                "days": {
                    "type": "integer",
                    "description": "Number of forecast days to include (1=today only, 2=today+tomorrow, etc.). Default 1.",
                },
            },
            "required": ["city"],
        },
    },
    {
        "name": "read_page",
        "description": (
            "Extract and return the readable text content of a webpage. "
            "Provide a URL to navigate to it first, or omit to read the current browser page. "
            "Use after open_url to read a page that's already open."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to navigate to and read (optional — omit to read current page)",
                },
            },
        },
    },
    {
        "name": "fill_form",
        "description": (
            "Fill in form fields on the currently open browser page. "
            "Use CSS selectors to identify fields (e.g. '#email', 'input[name=query]', '.search-box')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fields": {
                    "type": "object",
                    "description": "Map of CSS selector → value, e.g. {'#email': 'me@example.com', '#name': 'Purna Sai'}",
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["fields"],
        },
    },
    {
        "name": "click_element",
        "description": (
            "Click an element on the current browser page by its visible text or CSS selector. "
            "Examples: 'Search', 'Submit', 'Sign in', '#login-btn', 'button.submit'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Visible text or CSS selector of the element to click",
                },
            },
            "required": ["description"],
        },
    },
    {
        "name": "summarize_article",
        "description": (
            "Fetch a web article or page and return its text content for summarization. "
            "If the user says 'summarize this', 'summarize the article', 'summarize the page', "
            "'what does this page say', or refers to their current tab — omit the url parameter "
            "and the active Chrome tab URL will be used automatically. "
            "Only provide url if the user explicitly says a specific URL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full URL to fetch (omit to use the active Chrome tab automatically)",
                },
            },
        },
    },
    {
        "name": "summarize_youtube",
        "description": (
            "Get the transcript of a YouTube video and return it for summarization. "
            "If the user says 'summarize this video', 'what is this video about', "
            "'summarize the YouTube video', or refers to their current tab — omit the url parameter "
            "and the active Chrome tab URL will be used automatically. "
            "Only provide url if the user explicitly says a specific URL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "YouTube video URL (omit to use the active Chrome tab automatically)",
                },
            },
        },
    },
    {
        "name": "close_browser",
        "description": "Close the browser window.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]

HANDLERS = {
    "web_search": web_search,
    "get_weather": get_weather,
    "read_page": read_page,
    "fill_form": fill_form,
    "click_element": click_element,
    "summarize_article": summarize_article,
    "summarize_youtube": summarize_youtube,
    "close_browser": close_browser,
}
