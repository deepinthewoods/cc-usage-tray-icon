from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional, Tuple

# Cloudflare in front of claude.ai blocks plain `requests` based on TLS
# fingerprint. curl_cffi ships a vendored curl-impersonate so our handshake
# looks identical to a real Chrome browser.
from curl_cffi import requests

from .config import CACHE_DIR, BrowserConfig
from .models import State, UsageSnapshot

_IMPERSONATE = "chrome124"

log = logging.getLogger(__name__)

CLAUDE_BASE = "https://claude.ai"
# Cloudflare in front of claude.ai blocks tools with obviously-bot user agents
# (returns 403 on /api/organizations). Use a realistic Chrome UA.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
ORG_CACHE_PATH = CACHE_DIR / "org.json"

# Map config browser keys -> the string pycookiecheat expects.
_BROWSER_NAME = {
    "chrome": "Chrome",
    "chromium": "Chromium",
    "brave": "Brave",
    "vivaldi": "Vivaldi",
    "edge": "Edge",
    "slack": "Slack",
}

# Snap-installed browsers store profiles under ~/snap/<browser>/common/...
# pycookiecheat only knows about the standard XDG paths, so we probe these too.
_SNAP_COOKIE_PATHS = {
    "Chromium": [
        "~/snap/chromium/common/chromium/Default/Cookies",
        "~/snap/chromium/common/.config/chromium/Default/Cookies",
    ],
    "Chrome": [
        "~/snap/google-chrome/current/.config/google-chrome/Default/Cookies",
    ],
    "Brave": [
        "~/snap/brave/current/.config/BraveSoftware/Brave-Browser/Default/Cookies",
    ],
}


def _candidate_cookie_files(label: str, override: Optional[str]) -> Iterator[Optional[str]]:
    """Yield cookie_file paths to try for a given browser. None means use pycookiecheat default."""
    if override:
        yield override
        return
    yield None  # try the library's default first
    for p in _SNAP_COOKIE_PATHS.get(label, []):
        full = Path(p).expanduser()
        if full.exists():
            yield str(full)


class CookieDiscoveryError(RuntimeError):
    """Raised when no logged-in claude.ai session can be found."""


class UsageFetchError(RuntimeError):
    """Raised on transport failure or schema mismatch."""


class AuthExpiredError(UsageFetchError):
    """Raised when the cookie is rejected (401/403)."""


def discover_session_cookies(browser_cfg: BrowserConfig) -> Tuple[dict, str]:
    """Walk the configured browser list; return (cookie_dict, browser_label) on first hit."""
    try:
        from pycookiecheat import chrome_cookies  # type: ignore
    except ImportError as e:
        raise CookieDiscoveryError(
            "pycookiecheat is not installed — `pip install pycookiecheat`"
        ) from e

    last_error: Optional[Exception] = None
    override = browser_cfg.cookie_file_override.strip() or None

    for key in browser_cfg.order:
        label = _BROWSER_NAME.get(key.lower())
        if label is None:
            log.debug("Unknown browser key %r in config — skipping", key)
            continue

        for cookie_file in _candidate_cookie_files(label, override):
            kwargs: dict = {"browser": label}
            if cookie_file:
                kwargs["cookie_file"] = cookie_file
            location = cookie_file or "default path"
            try:
                cookies = chrome_cookies(CLAUDE_BASE, **kwargs)
            except Exception as e:
                last_error = e
                log.debug("Cookie lookup via %s (%s) failed: %s", label, location, e)
                continue
            if cookies and "sessionKey" in cookies:
                log.info("Loaded claude.ai session cookie from %s (%s)", label, location)
                return cookies, label
            # Opened the DB but no claude.ai session cookie present — common when the
            # user is logged in via a different browser. Surface so users can debug.
            log.info(
                "Opened %s cookie store at %s but no claude.ai sessionKey "
                "(not logged in via this browser?)",
                label, location,
            )

    # Optional Firefox fallback if installed
    if "firefox" in [b.lower() for b in browser_cfg.order]:
        try:
            import browser_cookie3  # type: ignore
        except ImportError:
            browser_cookie3 = None
            log.debug(
                "Firefox listed in config but browser-cookie3 not installed; "
                "install with: pipx inject ccstatuspanel browser-cookie3"
            )
        if browser_cookie3 is not None:
            try:
                jar = browser_cookie3.firefox(domain_name="claude.ai")
                cookies = {c.name: c.value for c in jar}
                if "sessionKey" in cookies:
                    log.info("Loaded claude.ai session cookie from Firefox")
                    return cookies, "Firefox"
                log.info("Opened Firefox cookie store but no claude.ai sessionKey")
            except Exception as e:
                last_error = e
                log.debug("Firefox cookie lookup failed: %s", e)

    msg = "No claude.ai session cookie found in any configured browser."
    if last_error:
        msg += f" Last error: {last_error}"
    msg += " Make sure you are logged in at https://claude.ai and your browser keyring is unlocked."
    raise CookieDiscoveryError(msg)


def _build_session(cookies: dict) -> requests.Session:
    s = requests.Session(impersonate=_IMPERSONATE)
    s.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"{CLAUDE_BASE}/settings/usage",
        "Origin": CLAUDE_BASE,
    })
    for name, value in cookies.items():
        s.cookies.set(name, value, domain=".claude.ai")
    return s


def _load_org_cache() -> Optional[str]:
    try:
        if ORG_CACHE_PATH.exists():
            return json.loads(ORG_CACHE_PATH.read_text()).get("org_id")
    except Exception as e:
        log.warning("Failed to read org cache: %s", e)
    return None


def _save_org_cache(org_id: str) -> None:
    try:
        ORG_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        ORG_CACHE_PATH.write_text(json.dumps({"org_id": org_id}))
    except Exception as e:
        log.warning("Failed to write org cache: %s", e)


def discover_org_id(session: requests.Session) -> str:
    cached = _load_org_cache()
    if cached:
        return cached
    url = f"{CLAUDE_BASE}/api/organizations"
    r = session.get(url, timeout=15)
    if r.status_code in (401, 403):
        raise AuthExpiredError(f"claude.ai rejected the session cookie ({r.status_code})")
    r.raise_for_status()
    try:
        orgs = r.json()
    except ValueError as e:
        raise UsageFetchError(f"/api/organizations did not return JSON: {e}") from e
    if not isinstance(orgs, list) or not orgs:
        raise UsageFetchError(f"/api/organizations returned unexpected payload: {orgs!r}")
    org_id = orgs[0].get("uuid") or orgs[0].get("id")
    if not org_id:
        raise UsageFetchError(f"Could not find org id in payload: {orgs[0]!r}")
    _save_org_cache(org_id)
    return org_id


def _parse_iso(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        # Handle trailing 'Z'
        v = value.replace("Z", "+00:00") if value.endswith("Z") else value
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _coerce_pct(value: object) -> float:
    """Accept either a 0-1 fraction or a 0-100 percent; return a 0-1 fraction."""
    if isinstance(value, bool):
        return 0.0
    if not isinstance(value, (int, float)):
        return 0.0
    v = float(value)
    if v > 1.0:
        v = v / 100.0
    return max(0.0, min(1.0, v))


def parse_usage_payload(payload: dict) -> UsageSnapshot:
    """Defensive parse — never raise on shape mismatch; return a usable snapshot."""
    if not isinstance(payload, dict):
        raise UsageFetchError(f"Usage payload is not an object: {type(payload).__name__}")

    five = payload.get("five_hour") or {}
    seven = payload.get("seven_day") or {}
    seven_opus = payload.get("seven_day_opus") or {}

    if not isinstance(five, dict) or not isinstance(seven, dict):
        raise UsageFetchError("Usage payload missing expected five_hour/seven_day fields")

    return UsageSnapshot(
        session_pct=_coerce_pct(five.get("utilization", five.get("percent", 0))),
        week_pct=_coerce_pct(seven.get("utilization", seven.get("percent", 0))),
        week_opus_pct=_coerce_pct(seven_opus.get("utilization", seven_opus.get("percent", 0))),
        resets_at=_parse_iso(five.get("resets_at") or five.get("reset_at") or five.get("resetAt")),
        state=State.OK,
        error_msg="",
        fetched_at=datetime.now(timezone.utc),
    )


def fetch_usage(browser_cfg: BrowserConfig) -> UsageSnapshot:
    """One-shot: discover cookie, get org, fetch usage. Raises on any failure."""
    cookies, _label = discover_session_cookies(browser_cfg)
    session = _build_session(cookies)

    org_id = discover_org_id(session)
    url = f"{CLAUDE_BASE}/api/organizations/{org_id}/usage"
    r = session.get(url, timeout=15)
    if r.status_code in (401, 403):
        # Cookie may be live but org cache could be stale; clear and surface.
        try:
            ORG_CACHE_PATH.unlink(missing_ok=True)
        except Exception:
            pass
        raise AuthExpiredError(f"claude.ai usage endpoint returned {r.status_code}")
    if r.status_code == 404:
        try:
            ORG_CACHE_PATH.unlink(missing_ok=True)
        except Exception:
            pass
        raise UsageFetchError("Usage endpoint 404 — org id may have changed; cache cleared")
    r.raise_for_status()

    try:
        payload = r.json()
    except ValueError as e:
        raise UsageFetchError(f"Usage endpoint did not return JSON: {e}") from e

    return parse_usage_payload(payload)
