# cc-usage-tray-icon

A Linux system-tray indicator that shows your **claude.ai usage** at a glance — two stacked horizontal bars (current 5-hour session + rolling 7-day weekly) and a countdown timer to the next session reset, all pinned to your top bar.

```
┌──────────────────────────────────────┐
│  [█████░░░░░░]   <- session 50%      │
│  [███░░░░░░░░]   <- week    30%      │
└──────────────────────────────────────┘
   right-click ↓
   ┌─────────────────────────┐
   │ Session: 50%            │
   │ Week: 31%               │
   │ Resets in: 1h 57m       │
   ├─────────────────────────┤
   │ Refresh now             │
   │ Open dashboard          │
   │ Open config             │
   ├─────────────────────────┤
   │ Quit                    │
   └─────────────────────────┘
```

The data comes from the same internal endpoint that backs https://claude.ai/settings/usage, so the numbers match the dashboard exactly.

## Status

⚠️ **Alpha.** The data source is **undocumented** — `claude.ai/api/organizations/{org}/usage` is not part of Anthropic's public API. It can change without notice. The app degrades gracefully (greyed icon + one notification) when the endpoint breaks, but the fix in that case is reading the new schema from your browser's network tab.

Anthropic has acknowledged the lack of an official endpoint; see [anthropics/claude-code#32796](https://github.com/anthropics/claude-code/issues/32796) and [#44328](https://github.com/anthropics/claude-code/issues/44328).

## Why this exists

If you're on a Pro or Max plan and want to pace your work against the 5-hour session and weekly limits, the only way today is to keep `claude.ai/settings/usage` open in a browser tab. This puts the same numbers in your top bar so you absorb them ambiently instead of context-switching.

## Requirements

- Linux desktop (developed on **Ubuntu 24.04 / GNOME 46 / X11**; should work on most modern distros — see [Compatibility](#compatibility))
- Python 3.11+
- A logged-in claude.ai session in **Chrome, Chromium (incl. snap), Brave**, or **Vivaldi** (Firefox optional, see below)
- A system tray that supports the AppIndicator / KStatusNotifierItem spec
- `pipx` (recommended) or `pip`

## Install

### 1. System packages

**Debian / Ubuntu:**

```bash
sudo apt install \
    gir1.2-ayatanaappindicator3-0.1 \
    python3-gi \
    gir1.2-gtk-3.0 \
    libsecret-1-0
```

**Fedora:**

```bash
sudo dnf install libappindicator-gtk3 python3-gobject gtk3 libsecret
```

**Arch:**

```bash
sudo pacman -S libappindicator-gtk3 python-gobject gtk3 libsecret
```

### 2. The app

```bash
pipx install git+https://github.com/deepinthewoods/cc-usage-tray-icon.git
```

`pipx` venvs don't see system Python packages by default. The AppIndicator backend needs the system `python3-gi`, so enable system-site-packages on the freshly created venv:

```bash
sed -i 's/^include-system-site-packages = false$/include-system-site-packages = true/' \
    ~/.local/share/pipx/venvs/ccstatuspanel/pyvenv.cfg
```

For Firefox cookie support add the optional dep:

```bash
pipx inject ccstatuspanel browser-cookie3
```

### 3. Run it

```bash
ccstatuspanel --install     # writes ~/.local/share/applications + autostart entry
ccstatuspanel               # launch
```

The autostart entry makes the indicator appear automatically on every login.

## Configuration

`~/.config/ccstatuspanel/config.toml` is written on first run with these defaults:

```toml
[plan]
tier = "max_5x"

[poll]
interval_seconds = 60
stale_after_failures = 3

[ui]
warn_threshold = 0.60       # bar turns amber at this fraction
crit_threshold = 0.85       # bar turns red at this fraction
show_timer_in_tooltip = true
icon_height_px = 22         # GNOME pins top-bar height ~22 px
icon_width_px = 72          # bump for wider bars (try 96 or 120)

[browser]
order = ["chrome", "chromium", "brave", "vivaldi"]
cookie_file_override = ""   # absolute path to a Cookies sqlite (snap, etc.)
```

Edit and `Refresh now` from the menu, or restart the app.

## How it works

```
┌─────────────────────────────────────────────────────────────┐
│  cc-usage-tray-icon                                         │
│                                                             │
│  ┌─────────────┐    ┌──────────────────┐    ┌─────────────┐ │
│  │ pycookie-   │--->│ curl_cffi        │--->│ claude.ai   │ │
│  │ cheat       │    │ (chrome impers.) │    │ /api/...    │ │
│  └─────────────┘    └──────────────────┘    └─────────────┘ │
│        ↑                     ↓                              │
│  browser cookie        usage JSON                           │
│  store (libsecret)                                          │
│                              ↓                              │
│             ┌─────────────────────────────┐                 │
│             │ poller (state machine)      │                 │
│             │   OK → DEGRADED → STALE     │                 │
│             └─────────────────────────────┘                 │
│                              ↓                              │
│             ┌─────────────────────────────┐                 │
│             │ tray (pystray + AppIndic.)  │                 │
│             │   Pillow render → top bar   │                 │
│             └─────────────────────────────┘                 │
└─────────────────────────────────────────────────────────────┘
```

1. **Cookie discovery** — [`pycookiecheat`](https://github.com/n8henrie/pycookiecheat) reads your logged-in `sessionKey` cookie from any of the configured browsers (probes both standard XDG paths and snap-confined paths). The cookie is decrypted via libsecret/GNOME Keyring.
2. **Cloudflare bypass** — claude.ai sits behind Cloudflare, which fingerprints the TLS handshake. Plain `requests` (and even raw `curl`) get a 403 challenge page even with valid cookies. We use [`curl_cffi`](https://github.com/yifeikong/curl_cffi) with `impersonate="chrome124"` so the handshake matches a real Chrome.
3. **Poll loop** — once a minute (configurable), fetches `/api/organizations/{org_id}/usage`. State machine: `OK → DEGRADED (1–2 transient failures, keep last values) → STALE (3+ failures, grey icon + one desktop notification)`.
4. **Render** — Pillow draws two horizontal bars at `icon_width_px × icon_height_px` (default 72×22, internally rendered at 2× for HiDPI). Colour: green (< warn), amber (≥ warn), red (≥ crit). Stale state = grey dashed outlines.
5. **Tray** — `pystray.Icon` mainloop on the AppIndicator backend; right-click menu shows live percentages and the countdown.

## Compatibility

| Environment | Tested | Notes |
|---|---|---|
| Ubuntu 24.04 / GNOME 46 / X11 | ✅ | Primary dev target. Ubuntu ships `gnome-shell-extension-appindicator` enabled by default. |
| Ubuntu 24.04 / GNOME 46 / Wayland | ⚠️ | Should work via XWayland; not extensively tested. |
| Fedora / Arch / Debian (vanilla GNOME) | ⚠️ | You need to install [AppIndicator and KStatusNotifierItem Support](https://extensions.gnome.org/extension/615/appindicator-support/) or GNOME's official Status Icons extension. |
| KDE Plasma | ⚠️ | KStatusNotifierItem is native; should work. Untested. |
| XFCE / Cinnamon / MATE | ⚠️ | All support AppIndicator. Untested. |

## Troubleshooting

### "No claude.ai session cookie found"

1. Make sure you're logged in to claude.ai in one of the browsers in `[browser].order`.
2. **Snap-installed Chromium** stores cookies under `~/snap/chromium/...`. The app probes this path automatically, but if you have a non-default profile, set:
   ```toml
   [browser]
   cookie_file_override = "/home/YOU/snap/chromium/common/chromium/Profile 2/Cookies"
   ```
3. **Keyring locked** (`libsecret` DBus error): unlock GNOME Keyring. It auto-unlocks at GUI login but stays locked under SSH/headless sessions.

### Icon doesn't appear in the top bar

- **Vanilla GNOME**: install the AppIndicator extension linked above.
- **AppIndicator backend not loading**: `pipx` venvs don't inherit the system `python3-gi`, which the AppIndicator backend needs. Confirm:
  ```bash
  ~/.local/share/pipx/venvs/ccstatuspanel/bin/python -c \
    "import gi; gi.require_version('AyatanaAppIndicator3', '0.1'); print('ok')"
  ```
  If that fails, edit `~/.local/share/pipx/venvs/ccstatuspanel/pyvenv.cfg` and set `include-system-site-packages = true`, then re-run `ccstatuspanel`.

### Numbers don't match the dashboard

The app queries the same endpoint the dashboard uses, so values should match within rounding (the response gives utilization as a 0–100 number that we display as an integer). If they diverge significantly, the response shape may have changed — please [open an issue](https://github.com/deepinthewoods/cc-usage-tray-icon/issues) with the output of `ccstatuspanel --verbose`.

### Hover tooltips don't show on GNOME

This is a long-standing GNOME shell limitation — the AppIndicator extension treats `set_title` as accessibility text, not a hover tooltip. Use **right-click** to see the live percentages instead. (PRs welcome to render the percentages directly into the icon image as a fallback.)

## Privacy

- The app reads cookies for `https://claude.ai` only — never any other origin.
- The only network destination is `https://claude.ai/api/...`.
- Nothing is sent anywhere else. No analytics, no telemetry, no auto-updates.
- Cookie reading happens in-process via `pycookiecheat`; the cookie value is held in memory only for the duration of the request.

## Development

```bash
git clone https://github.com/deepinthewoods/cc-usage-tray-icon.git
cd cc-usage-tray-icon
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
```

The project is laid out as:

```
src/ccstatuspanel/
  app.py          — entry point, wires threads + tray
  config.py       — TOML load/save
  claude_api.py   — cookie discovery + curl_cffi HTTP client
  poller.py       — OK/DEGRADED/STALE state machine
  icon.py         — Pillow renderer
  tray.py         — pystray + menu
  notify.py       — notify-send wrapper
  installer.py    — XDG desktop entry / autostart
  models.py       — UsageSnapshot dataclass
tests/
  test_*.py       — 24 tests, no network needed
```

## Contributing

Bug reports and PRs welcome. The most fragile part is `claude_api.py`'s assumption about the response schema — if Anthropic ships a change, please open an issue with a sample of the new payload (you can grab it via `Network` tab on `claude.ai/settings/usage`).

## License

MIT
