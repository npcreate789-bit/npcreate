"""TikTok Live Screen-Share auto-controller — ported from legacy
``vcam-pc/src/tiktok_controller.py``.

Walks the TikTok app's UI via ``uiautomator dump`` + ``input tap`` to drive::

    Home → [+] (Create) → "Live" tab → "Go Live" → "Screen Share" → "Start Now"

The Live → Screen-Share path captures the phone's display via
MediaProjection. If our receiver app is in fullscreen Live Mode at the
same time, the broadcast pixels equal the streamed video — no root, no
camera HAL involvement.

The matcher is intentionally fragile-tolerant:

- Match by *text* or *content-desc* substring (case-insensitive), not by
  fixed coordinates. TikTok rearranges its UI every few versions.
- Multilingual keyword sets (en / th / zh) so Thai/global/Douyin builds all work.
- ``prefer_short`` heuristic to avoid matching "Live cooking show by @chef"
  thumbnail labels when we wanted the 4-char "LIVE" tab.
- A coordinate fallback for the [+] Create button (some Aweme builds don't
  set a11y labels on the icon).

By default ``run_to_screen_share`` stops one tap before "Start Now" so the
user has a final confirmation chance. Pass ``confirm_start=True`` to go fully
automatic.
"""
from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .adb_service import AdbService

log = logging.getLogger(__name__)

# Order matters — try each variant; the first matching ``pm list packages``
# entry wins. ``trill`` is the TikTok build distributed in Thailand / SEA.
TIKTOK_PACKAGES: tuple[str, ...] = (
    "com.ss.android.ugc.trill",          # TikTok Global / Thai
    "com.zhiliaoapp.musically",          # TikTok Global / US
    "com.zhiliaoapp.musically.go",       # TikTok Lite
    "com.ss.android.ugc.aweme",          # Douyin (China)
    "com.ss.android.ugc.aweme.lite",     # Douyin Lite
)

KW_LIVE_TAB = ("live", "ไลฟ์", "直播")
KW_GO_LIVE = (
    "go live", "go-live", "start live",
    "เริ่มไลฟ์", "ไปไลฟ์", "เริ่มสด", "ถ่ายทอดสด", "ออกอากาศ",
    "开始直播", "开播", "開始直播", "開播",
)
KW_SCREEN_SHARE = (
    "screen share", "share screen", "screenshare", "share your screen",
    "แชร์หน้าจอ", "หน้าจอ", "屏幕共享", "分享屏幕",
)
KW_CONFIRM_START = (
    "start now", "start broadcast", "start", "go live",
    "เริ่มเลย", "เริ่ม", "ตกลง", "อนุญาต", "allow", "ok",
)
KW_CREATE_BUTTON = ("create", "สร้าง", "创建", "+")

DUMP_PATH_PHONE = "/sdcard/vcam_uidump.xml"

# Tap the bottom of the screen at ~96 % height when the [+] button has no a11y label.
_BOTTOM_TAP_HEIGHT_FRAC = 0.96


@dataclass(frozen=True)
class StepResult:
    name: str
    ok: bool
    detail: str = ""


def find_node(
    xml: str,
    keywords: Iterable[str],
    *,
    prefer_short: bool = True,
) -> tuple[int, int] | None:
    """Return the centre (x, y) of the first clickable node whose ``text=``
    or ``content-desc=`` matches any keyword (case-insensitive substring).

    ``prefer_short=True`` resolves ambiguity by picking the shortest label —
    a deliberate trade-off that avoids tapping livestream thumbnails whose
    long content-desc happens to contain "live".
    """
    pattern = re.compile(
        r'(?:text|content-desc)="([^"]+)"[^>]*?'
        r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        re.IGNORECASE,
    )
    keyword_list = [k.lower() for k in keywords]
    matches: list[tuple[str, int, int, int, int]] = []
    for label, x1, y1, x2, y2 in pattern.findall(xml):
        low = label.strip().lower()
        if not low:
            continue
        if any(kw in low for kw in keyword_list):
            matches.append((label, int(x1), int(y1), int(x2), int(y2)))
    if not matches:
        return None
    if prefer_short:
        matches.sort(key=lambda m: len(m[0]))
    _label, x1, y1, x2, y2 = matches[0]
    return (x1 + x2) // 2, (y1 + y2) // 2


def parse_screen_size(wm_size_output: str) -> tuple[int, int] | None:
    """Parse the output of ``wm size``. Prefers ``Override size`` when present
    (that's the active size used for input mapping)."""
    if not wm_size_output:
        return None
    override = re.search(r"override\s*size:\s*(\d+)\s*x\s*(\d+)", wm_size_output, re.IGNORECASE)
    if override:
        return int(override.group(1)), int(override.group(2))
    physical = re.search(r"physical\s*size:\s*(\d+)\s*x\s*(\d+)", wm_size_output, re.IGNORECASE)
    if physical:
        return int(physical.group(1)), int(physical.group(2))
    generic = re.search(r"(\d+)\s*x\s*(\d+)", wm_size_output)
    if generic:
        return int(generic.group(1)), int(generic.group(2))
    return None


def parse_installed_packages(pm_output: str) -> set[str]:
    """Parse output of ``pm list packages -e``."""
    out: set[str] = set()
    for line in pm_output.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            out.add(line.removeprefix("package:").strip())
    return out


class TikTokAutomation:
    """Drive the TikTok app via uiautomator + tap commands."""

    def __init__(
        self,
        adb: AdbService,
        *,
        tap_settle_s: float = 1.5,
        scroll_attempts: int = 3,
        log_callback: Callable[[str], None] | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.adb = adb
        self.tap_settle_s = tap_settle_s
        self.scroll_attempts = scroll_attempts
        self.log_callback = log_callback
        self._sleep = sleep_fn

    # -- helpers ----------------------------------------------------------

    def _emit(self, msg: str) -> None:
        log.info(msg)
        if self.log_callback:
            try:
                self.log_callback(msg)
            except Exception:
                log.debug("log_callback failed", exc_info=True)

    # -- package + launch ------------------------------------------------

    def find_installed_package(self) -> str | None:
        result = self.adb.exec_argv("shell", "pm", "list", "packages", "-e", timeout=8.0)
        if result.returncode != 0:
            return None
        installed = parse_installed_packages(result.stdout)
        for package in TIKTOK_PACKAGES:
            if package in installed:
                return package
        return None

    def launch(self, package: str) -> StepResult:
        result = self.adb.exec_argv(
            "shell", "monkey", "-p", package,
            "-c", "android.intent.category.LAUNCHER", "1",
            timeout=8.0,
        )
        self._sleep(2.0)
        if result.returncode == 0:
            return StepResult("launch", True, package)
        return StepResult("launch", False, f"monkey failed (rc={result.returncode})")

    # -- ui dump + element search ----------------------------------------

    def dump_ui(self) -> str | None:
        """Try compressed mode first (skips layout-only nodes and doesn't
        wait for idle — TikTok's For You feed is never idle). Fall back to
        plain dump on the very rare Android < 5 devices."""
        for argv in (
            ("shell", "uiautomator", "dump", "--compressed", DUMP_PATH_PHONE),
            ("shell", "uiautomator", "dump", DUMP_PATH_PHONE),
        ):
            r = self.adb.exec_argv(*argv, timeout=6.0)
            if r.returncode == 0:
                break
        else:
            return None
        cat = self.adb.exec_argv("shell", "cat", DUMP_PATH_PHONE, timeout=4.0)
        if cat.returncode != 0 or not cat.stdout:
            return None
        return cat.stdout

    def screen_size(self) -> tuple[int, int] | None:
        r = self.adb.exec_argv("shell", "wm", "size", timeout=3.0)
        if r.returncode != 0:
            return None
        return parse_screen_size(r.stdout)

    def tap(self, x: int, y: int, *, settle: bool = True) -> bool:
        r = self.adb.exec_argv("shell", "input", "tap", str(x), str(y), timeout=4.0)
        if settle:
            self._sleep(self.tap_settle_s)
        return r.returncode == 0

    def _swipe_up_for_more(self) -> None:
        """Reveal more options on TikTok Live screens that hide Screen Share
        below the fold for first-time users."""
        self.adb.exec_argv(
            "shell", "input", "swipe", "540", "1500", "540", "800", "300",
            timeout=4.0,
        )
        self._sleep(0.6)

    def _find_or_scroll(self, keywords: Iterable[str], label: str) -> tuple[int, int] | None:
        for attempt in range(self.scroll_attempts + 1):
            xml = self.dump_ui()
            if xml is None:
                self._emit(f"  [{label}] couldn't dump UI (try {attempt + 1})")
                self._sleep(1.0)
                continue
            xy = find_node(xml, keywords)
            if xy is not None:
                return xy
            if attempt < self.scroll_attempts:
                self._emit(f"  [{label}] not found, scrolling…")
                self._swipe_up_for_more()
        return None

    def _tap_create_button(self) -> bool:
        """Find and tap the bottom-nav [+] Create button.

        Strategy: try a11y label first; fall back to bottom-centre at ~96 %
        of screen height. ``wm size`` covers any aspect ratio; a hardcoded
        540×2300 covers the case where ``wm size`` also fails.
        """
        xml = self.dump_ui()
        xy: tuple[int, int] | None = None
        if xml:
            xy = find_node(xml, KW_CREATE_BUTTON, prefer_short=True)
        if xy is None:
            size = self.screen_size()
            if size is not None:
                xy = (size[0] // 2, int(size[1] * _BOTTOM_TAP_HEIGHT_FRAC))
                self._emit(f"  [Create] no labelled [+] node — tapping bottom-centre @{xy} ({size[0]}x{size[1]})")
            else:
                xy = (540, 2300)
                self._emit(f"  [Create] no [+] node and wm size failed — using hardcoded fallback @{xy}")
        ok = self.tap(*xy)
        if ok:
            self._emit(f"→ tapped Create [+] @{xy}")
        else:
            self._emit(f"✗ tap on Create [+] failed @{xy}")
        return ok

    # -- orchestration ----------------------------------------------------

    def run_to_screen_share(self, *, confirm_start: bool = False) -> list[StepResult]:
        """Walk the full flow. Stops one tap before Start Now by default."""
        results: list[StepResult] = []

        # 1. find + launch TikTok
        package = self.find_installed_package()
        if not package:
            results.append(StepResult("find_package", False, "no TikTok variant installed"))
            self._emit("✗ no TikTok variant installed")
            return results
        self._emit(f"→ TikTok package: {package}")
        results.append(StepResult("find_package", True, package))

        launch_result = self.launch(package)
        results.append(launch_result)
        if not launch_result.ok:
            self._emit(f"✗ launch failed: {launch_result.detail}")
            return results
        self._emit("→ TikTok launched")
        self._sleep(2.5)

        # 2. tap [+] Create to leave For You feed
        self._tap_create_button()
        self._sleep(2.0)

        # 3. LIVE tab on create screen
        live_xy = self._find_or_scroll(KW_LIVE_TAB, "Live tab")
        if live_xy is None:
            results.append(StepResult(
                "live_tab", False,
                "หาแท็บ LIVE ไม่เจอ — เปิด TikTok แล้วกด [+] ให้เห็น LIVE/VIDEO/STORY ก่อน",
            ))
            self._emit("✗ Live tab not located after [+] tap")
            return results
        self.tap(*live_xy)
        results.append(StepResult("live_tab", True, f"@({live_xy[0]},{live_xy[1]})"))
        self._emit(f"→ tapped Live tab @{live_xy}")

        # 4. Go Live / Start Live button
        go_xy = self._find_or_scroll(KW_GO_LIVE, "Go Live")
        if go_xy is None:
            results.append(StepResult(
                "go_live", False,
                "Go-Live ไม่เจอ — บัญชี TikTok อาจไม่มีสิทธิ์ Live ในภูมิภาคนี้",
            ))
            self._emit("✗ Go Live not found")
            return results
        self.tap(*go_xy)
        results.append(StepResult("go_live", True, f"@({go_xy[0]},{go_xy[1]})"))
        self._emit(f"→ tapped Go Live @{go_xy}")

        # 5. Screen Share mode
        ss_xy = self._find_or_scroll(KW_SCREEN_SHARE, "Screen Share")
        if ss_xy is None:
            results.append(StepResult(
                "screen_share", False,
                "Screen-Share toggle ไม่เจอ — TikTok อาจปิดในภูมิภาคนี้ หรือบัญชีไม่ผ่านเงื่อนไข",
            ))
            self._emit("✗ Screen Share not found")
            return results
        self.tap(*ss_xy)
        results.append(StepResult("screen_share", True, f"@({ss_xy[0]},{ss_xy[1]})"))
        self._emit(f"→ tapped Screen Share @{ss_xy}")

        # 6. Start Now — only if user opted in
        if not confirm_start:
            results.append(StepResult(
                "start_now", True,
                "หยุดก่อน Start Now — ผู้ใช้กดยืนยันเอง หลังเปิด Live Mode บนตัวรับ",
            ))
            self._emit("→ stopped one tap short")
            return results

        sn_xy = self._find_or_scroll(KW_CONFIRM_START, "Start Now")
        if sn_xy is None:
            results.append(StepResult("start_now", False, "Start-Now ไม่เจอ"))
            return results
        self.tap(*sn_xy)
        results.append(StepResult("start_now", True, f"@({sn_xy[0]},{sn_xy[1]})"))
        self._emit("→ broadcast started")
        return results
