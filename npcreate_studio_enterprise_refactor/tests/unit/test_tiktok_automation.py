"""Phase B1 — TikTok automation tests.

Real ``uiautomator dump`` / ``input tap`` aren't reachable in CI, so we stub
``AdbService`` at the public surface (``exec_argv``) and feed canned outputs.
Pure helpers (find_node, parse_screen_size, parse_installed_packages) are
exercised directly against fixture strings.
"""
from __future__ import annotations

from collections.abc import Sequence

from npcreate_studio.infrastructure.subprocess_runner import CommandResult
from npcreate_studio.services.tiktok_automation import (
    KW_CREATE_BUTTON,
    KW_LIVE_TAB,
    TIKTOK_PACKAGES,
    TikTokAutomation,
    find_node,
    parse_installed_packages,
    parse_screen_size,
)

# ---------- pure helpers ----------


def test_find_node_returns_centre_of_first_match():
    xml = '<node text="LIVE" bounds="[100,200][300,400]" />'
    assert find_node(xml, ["live"]) == (200, 300)


def test_find_node_handles_content_desc_attribute():
    xml = '<node content-desc="Create" bounds="[10,20][30,40]" />'
    assert find_node(xml, ["create"]) == (20, 30)


def test_find_node_returns_none_when_no_match():
    xml = '<node text="Home" bounds="[0,0][100,100]"/>'
    assert find_node(xml, ["live"]) is None


def test_find_node_prefer_short_picks_shorter_label_first():
    """Two matches: short tab "LIVE" + long thumbnail "Live cooking show by @chef".
    The shorter wins so we don't tap a livestream preview by accident."""
    xml = (
        '<node text="LIVE" bounds="[100,200][140,240]"/>'
        '<node content-desc="Live cooking show by @chef" bounds="[400,500][800,560]"/>'
    )
    assert find_node(xml, ["live"]) == (120, 220)


def test_find_node_without_prefer_short_picks_first_in_document_order():
    xml = (
        '<node content-desc="Live cooking show by @chef" bounds="[400,500][800,560]"/>'
        '<node text="LIVE" bounds="[100,200][140,240]"/>'
    )
    # prefer_short=False → document order wins → the longer label
    assert find_node(xml, ["live"], prefer_short=False) == (600, 530)


def test_find_node_case_insensitive_keyword_match():
    xml = '<node text="ไลฟ์" bounds="[100,200][140,240]"/>'
    # Keyword "live" should not match Thai — only Thai keyword does.
    assert find_node(xml, ["LIVE"]) is None
    assert find_node(xml, ["ไลฟ์"]) == (120, 220)


def test_find_node_skips_empty_labels():
    xml = '<node text="" bounds="[100,200][140,240]"/>'
    assert find_node(xml, ["live"]) is None


# ---------- parse_screen_size ----------


def test_parse_screen_size_prefers_override():
    out = "Physical size: 1080x2400\nOverride size: 720x1600\n"
    assert parse_screen_size(out) == (720, 1600)


def test_parse_screen_size_falls_back_to_physical():
    assert parse_screen_size("Physical size: 1080x2400") == (1080, 2400)


def test_parse_screen_size_returns_none_for_empty():
    assert parse_screen_size("") is None
    assert parse_screen_size("garbage") is None


def test_parse_screen_size_generic_fallback():
    assert parse_screen_size("Size: 720x1280") == (720, 1280)


# ---------- parse_installed_packages ----------


def test_parse_installed_packages_basic():
    out = "package:com.ss.android.ugc.trill\npackage:com.example.foo\n"
    parsed = parse_installed_packages(out)
    assert "com.ss.android.ugc.trill" in parsed
    assert "com.example.foo" in parsed


def test_parse_installed_packages_ignores_non_package_lines():
    out = "Hello world\npackage:com.x.y\nblah\n"
    assert parse_installed_packages(out) == {"com.x.y"}


def test_parse_installed_packages_empty():
    assert parse_installed_packages("") == set()


# ---------- TikTokAutomation (via fake AdbService) ----------


class _FakeAdb:
    """Stub that returns canned CommandResult per matched argv suffix."""

    def __init__(self) -> None:
        self.calls: list[Sequence[str]] = []
        self._matchers: list[tuple[tuple[str, ...], CommandResult]] = []
        self.default: CommandResult = CommandResult(0, "", "")

    def register(self, suffix: Sequence[str], result: CommandResult) -> None:
        self._matchers.append((tuple(suffix), result))

    def exec_argv(self, *args: str, serial: str | None = None, timeout: float = 10.0) -> CommandResult:
        argv = tuple(str(a) for a in args)
        self.calls.append(argv)
        for suffix, result in self._matchers:
            if argv[-len(suffix):] == suffix:
                return result
        return self.default


def _automation(adb: _FakeAdb) -> TikTokAutomation:
    return TikTokAutomation(
        adb=adb,  # type: ignore[arg-type]
        tap_settle_s=0.0,
        scroll_attempts=1,
        sleep_fn=lambda _s: None,
    )


def test_find_installed_package_picks_first_matching_variant():
    adb = _FakeAdb()
    adb.register(("packages", "-e"), CommandResult(0, "package:com.zhiliaoapp.musically\n", ""))
    auto = _automation(adb)
    pkg = auto.find_installed_package()
    assert pkg == "com.zhiliaoapp.musically"


def test_find_installed_package_returns_none_when_no_variant_found():
    adb = _FakeAdb()
    adb.register(("packages", "-e"), CommandResult(0, "package:com.unrelated\n", ""))
    auto = _automation(adb)
    assert auto.find_installed_package() is None


def test_find_installed_package_respects_priority_order():
    adb = _FakeAdb()
    # Output has TWO variants installed; the first one in TIKTOK_PACKAGES must win.
    adb.register(
        ("packages", "-e"),
        CommandResult(
            0,
            "package:com.zhiliaoapp.musically\npackage:com.ss.android.ugc.trill\n",
            "",
        ),
    )
    auto = _automation(adb)
    assert auto.find_installed_package() == TIKTOK_PACKAGES[0]  # trill before musically


def test_launch_returns_ok_when_monkey_succeeds():
    adb = _FakeAdb()
    adb.default = CommandResult(0, "Events injected: 1", "")
    auto = _automation(adb)
    result = auto.launch("com.ss.android.ugc.trill")
    assert result.name == "launch"
    assert result.ok is True
    assert "trill" in result.detail


def test_launch_returns_failure_on_monkey_nonzero():
    adb = _FakeAdb()
    adb.default = CommandResult(1, "", "Error: no such activity")
    auto = _automation(adb)
    result = auto.launch("com.example.nope")
    assert result.ok is False
    assert "rc=1" in result.detail


def test_dump_ui_uses_compressed_then_cat():
    adb = _FakeAdb()
    adb.register(("dump", "--compressed", "/sdcard/vcam_uidump.xml"), CommandResult(0, "ok", ""))
    adb.register(("cat", "/sdcard/vcam_uidump.xml"), CommandResult(0, "<hierarchy/>", ""))
    auto = _automation(adb)
    xml = auto.dump_ui()
    assert xml == "<hierarchy/>"


def test_dump_ui_returns_none_when_cat_fails():
    adb = _FakeAdb()
    adb.register(("dump", "--compressed", "/sdcard/vcam_uidump.xml"), CommandResult(0, "ok", ""))
    adb.register(("cat", "/sdcard/vcam_uidump.xml"), CommandResult(1, "", "no such file"))
    auto = _automation(adb)
    assert auto.dump_ui() is None


def test_screen_size_returns_override_when_present():
    adb = _FakeAdb()
    adb.register(("wm", "size"), CommandResult(0, "Physical size: 1080x2400\nOverride size: 720x1600\n", ""))
    auto = _automation(adb)
    assert auto.screen_size() == (720, 1600)


def test_screen_size_returns_none_on_failure():
    adb = _FakeAdb()
    adb.register(("wm", "size"), CommandResult(1, "", ""))
    auto = _automation(adb)
    assert auto.screen_size() is None


def test_tap_invokes_input_tap_with_coordinates():
    adb = _FakeAdb()
    auto = _automation(adb)
    assert auto.tap(123, 456, settle=False) is True
    # Last call must be `input tap 123 456`
    last = adb.calls[-1]
    assert last[-4:] == ("input", "tap", "123", "456")


def test_run_to_screen_share_happy_path_without_confirm_start():
    """Walk every UI step where each dump_ui returns XML containing the
    expected keyword; we should end with status reaching 'screen_share'
    and stopping before start_now."""
    adb = _FakeAdb()
    # Package lookup
    adb.register(("packages", "-e"), CommandResult(0, "package:com.ss.android.ugc.trill\n", ""))
    # monkey launch
    adb.register(("monkey", "-p", "com.ss.android.ugc.trill", "-c", "android.intent.category.LAUNCHER", "1"), CommandResult(0, "", ""))
    # All `uiautomator dump --compressed` calls succeed
    adb.register(("dump", "--compressed", "/sdcard/vcam_uidump.xml"), CommandResult(0, "ok", ""))
    # We don't differentiate per-step here — return XML that satisfies the
    # first keyword check at any point. Use a permissive XML that contains
    # every keyword we look for.
    xml_payload = (
        '<node content-desc="Create" bounds="[10,20][30,40]"/>'
        '<node text="LIVE" bounds="[100,200][140,240]"/>'
        '<node text="Go Live" bounds="[200,500][400,560]"/>'
        '<node text="Screen Share" bounds="[300,800][500,860]"/>'
    )
    adb.register(("cat", "/sdcard/vcam_uidump.xml"), CommandResult(0, xml_payload, ""))
    auto = _automation(adb)
    results = auto.run_to_screen_share(confirm_start=False)
    names = [r.name for r in results]
    assert names == ["find_package", "launch", "live_tab", "go_live", "screen_share", "start_now"]
    final = {r.name: r for r in results}
    assert final["find_package"].ok
    assert final["launch"].ok
    assert final["live_tab"].ok
    assert final["go_live"].ok
    assert final["screen_share"].ok
    # start_now is "ok=True" because we intentionally stopped one tap short
    # (the caller is expected to confirm manually). The detail explains it.
    assert final["start_now"].ok is True
    assert "Start Now" in final["start_now"].detail or "ผู้ใช้กดยืนยันเอง" in final["start_now"].detail


def test_run_to_screen_share_aborts_when_no_tiktok_installed():
    adb = _FakeAdb()
    adb.register(("packages", "-e"), CommandResult(0, "", ""))
    auto = _automation(adb)
    results = auto.run_to_screen_share()
    assert [r.name for r in results] == ["find_package"]
    assert results[0].ok is False


def test_run_to_screen_share_aborts_when_live_tab_not_found():
    adb = _FakeAdb()
    adb.register(("packages", "-e"), CommandResult(0, "package:com.ss.android.ugc.trill\n", ""))
    adb.register(("dump", "--compressed", "/sdcard/vcam_uidump.xml"), CommandResult(0, "ok", ""))
    # XML lacks any LIVE-tab keyword
    adb.register(("cat", "/sdcard/vcam_uidump.xml"), CommandResult(0, "<hierarchy/>", ""))
    adb.default = CommandResult(0, "", "")
    auto = _automation(adb)
    results = auto.run_to_screen_share()
    names = [r.name for r in results]
    assert names[-1] == "live_tab"
    assert results[-1].ok is False


def test_run_to_screen_share_does_full_walk_when_confirm_start_true():
    adb = _FakeAdb()
    adb.register(("packages", "-e"), CommandResult(0, "package:com.ss.android.ugc.trill\n", ""))
    adb.register(("dump", "--compressed", "/sdcard/vcam_uidump.xml"), CommandResult(0, "ok", ""))
    xml = (
        '<node content-desc="Create" bounds="[10,20][30,40]"/>'
        '<node text="LIVE" bounds="[100,200][140,240]"/>'
        '<node text="Go Live" bounds="[200,500][400,560]"/>'
        '<node text="Screen Share" bounds="[300,800][500,860]"/>'
        '<node text="Start Now" bounds="[500,1500][700,1560]"/>'
    )
    adb.register(("cat", "/sdcard/vcam_uidump.xml"), CommandResult(0, xml, ""))
    auto = _automation(adb)
    results = auto.run_to_screen_share(confirm_start=True)
    final = {r.name: r for r in results}
    assert final["start_now"].ok is True
    # Detail must point at coordinates, indicating an actual tap.
    assert "@(" in final["start_now"].detail


def test_log_callback_receives_step_messages():
    received: list[str] = []
    adb = _FakeAdb()
    adb.register(("packages", "-e"), CommandResult(0, "", ""))
    auto = TikTokAutomation(
        adb=adb,  # type: ignore[arg-type]
        tap_settle_s=0.0,
        scroll_attempts=0,
        sleep_fn=lambda _s: None,
        log_callback=received.append,
    )
    auto.run_to_screen_share()
    assert any("TikTok variant" in msg or "no TikTok" in msg or "no TikTok variant installed" in msg for msg in received)


# ---------- keyword sanity ----------


def test_keyword_sets_cover_required_languages():
    """We bundle en/th/zh. Confirm at least one entry per language so an
    accidental copy-paste loss is caught."""
    for kws, key in [(KW_LIVE_TAB, "ไลฟ์"), (KW_LIVE_TAB, "直播"), (KW_LIVE_TAB, "live")]:
        assert key in kws


def test_create_button_keywords_include_plus_glyph():
    assert "+" in KW_CREATE_BUTTON
