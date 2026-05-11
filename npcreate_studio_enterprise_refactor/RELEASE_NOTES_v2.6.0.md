# NP Create Studio v2.6.0 — Client Stack Feature Parity Release

**Release date:** 2026-05-11
**Previous version:** v2.5.0

Where v2.5.0 closed the backend / server hardening gaps, v2.6.0 closes
the **client-side feature gap** with the legacy `livemobillrerun`
codebase. Every workflow a customer relied on in legacy — streaming
video to a phone via FFmpeg, the 1-click TikTok Live Screen-Share
launch, per-device rotation presets, scrcpy mirror, RTMP push to remote
ingest, signed self-updates, and portable state backup — is now wired,
tested, and behind toast-feedback UI in the refactor.

The Android receiver app moved to **its own sibling repo**
(`npcreate_studio_android`) so the Python and Kotlin sides can ship
independently while keeping a single, documented wire-protocol contract.

The system is now **feature-complete for the customer pilot**. Outside
of the v2.5.0 "Known limits" list (payment merchant verification, real
Windows code-signing certificate, DPAPI binding for `SecureStore`), no
legacy-equivalent workflow remains unported.

---

## Highlights

- **15 phases delivered** across two sessions, all behind passing tests
  on every commit: **A1–A3** (streaming + ADB + health), **B1–B3**
  (TikTok automation + device profiles + scrcpy mirror), **C1–C6**
  (Live / Devices / Stream / Onboarding / Profiles / wiring), **D**
  (Android receiver in a new sibling repo), and **E1–E2** (auto-update
  orchestrator + backup hardening).
- **Test suite: 152 → 416 tests** (+264). All pass on Python
  3.11 / 3.12 / 3.13 plus the four Postgres-integration tests against
  Postgres 16.
- **Client GUI now ships the full operator surface**: a 5-step
  onboarding wizard does first-run setup; Live Streaming starts an
  FFmpeg pipeline, a 1-client TCP server, and an 8-second stall
  watchdog with one click; Devices renders authorized phones with
  per-row Mirror buttons; Profiles is a full CRUD editor for the
  per-device rotation library; Stream pushes the same source to an
  external RTMP URL; Backup / Restore wraps everything portable
  into a USB-stick-able ZIP.
- **Android receiver lives in a separate repo** at
  `../npcreate_studio_android` with package
  `com.npcreate.studio.receiver`. It speaks the same raw H.264
  Annex-B over `adb reverse tcp:8888` and writes the same
  16-byte-header YUV file the Python `HealthMonitor` reads.
- **Auto-update is wired end-to-end** for the customer machine: a
  daemon poller calls the existing `UpdateClient` every 6 hours, dedups
  by version, verifies the Ed25519 signature, and surfaces a toast.
  Manual "Check now" runs the same path on a worker thread. The new
  `apply_source_patch()` does an atomic `src/` swap with `src.bak`
  rollback; `relaunch()` spawns a fresh PID and exits.

---

## Breaking changes

None for v2.5.0 client code paths. All v2.6.0 work is additive: new
services, new pages, new sidebar entries. Existing pages that were
stubs in v2.5.0 (Live Streaming, Devices, Update Center) now have
implementations, but they keep the same module names and entry points.

The `BackupService` constructor signature changed from
`(project_root, app_data_dir)` to `(app_data_dir, *, app_name,
app_version)`. There are no existing callers in the tree, so this is
a refactor of a never-shipped API rather than a customer-facing break.

---

## What's new

### Streaming stack (Phase A1–A3)

Ported and hardened from `legacy/vcam-pc/src/streaming.py` and
`adb_helper.py`:

- **`StreamingSubprocess`** — `Popen` wrapper with an allowlist policy
  (`StreamingPolicy`), capture-output mode, and a detached "fire and
  forget" mode. Subprocess startup is logged with the redacted argv
  (any vendor flag containing `key=` / `token=` / `secret=` is masked).
- **`stream_server.py`** — TCP forwarder with a strict 1-client policy.
  When a second client tries to connect, the existing one is closed
  cleanly. Bind defaults to `127.0.0.1:8888`; `0.0.0.0` is rejected
  at startup unless the env is explicitly `development`.
- **`StreamingOrchestrator`** — façade combining `MediaService.build_pipe_args()`
  (H.264 → `pipe:1` Annex-B) with `streaming_subprocess` + `stream_server`.
  Exposes `start() / stop() / is_running() / stats` for the UI.
- **`AdbService`** — `list_devices`, `reverse(port, serial=)`,
  `reverse_list`, `shell`, `get_props`, plus a public `exec_argv()` so
  other services (like `MirrorService`) can compose `adb` commands
  without touching the binary path.
- **`HealthMonitor`** — background poller (2 s) that pulls the YUV file
  off the phone via `run-as <package> stat`, reads the 16-byte header,
  and surfaces stall detection (no frame counter change for ≥ 8 s).
  The Android receiver writes to the matching path
  (`/data/data/com.npcreate.studio.receiver/files/vcam.yuv`).

### Device profiles + automation (Phase B1–B3)

- **`DeviceProfileLibrary`** — frozen `DeviceProfile` dataclasses with
  `ProfileSource.BUILTIN / USER`, `add()` replace-by-name semantics,
  `find_by_model()` case-insensitive lookup, and `merge(builtin, user)`
  with user-overrides-by-name priority. A `Generic / unknown` fallback
  is always present in `library.profiles`.
- **`device_profile_repository.py`** — JSON load/save with atomic
  `.tmp` + rename, corrupt-file graceful fallback, and `auto_detect`
  that reads `ro.product.model` and falls back to Generic on any miss.
- **`TikTokAutomation`** — uiautomator UI walker that taps through to
  TikTok's "Live → Screen Share" mode without the operator needing to
  navigate manually. Step timing is generous (1.5 s per tap) and the
  walker re-reads the dump after every action; failures abort cleanly
  with a Thai toast.
- **`MirrorService`** — per-device scrcpy session manager. `start(serial)`
  spawns `scrcpy -s <serial>` as a detached child; `stop_all()` is
  called on `WM_DELETE_WINDOW` so windows don't outlive the host app.

### Client UI pages (Phase C1–C6)

- **Live Streaming (`live_page`)** — picks a source video, shows the
  current pipeline stats from `orchestrator.stats`, exposes a 🎬 TikTok
  button that runs the uiautomator walker on a worker thread, and
  renders the latest `HealthMonitor` status. Toast for every success /
  failure.
- **Devices (`devices_page`)** — renders every authorized device as a
  card with state pill, model, serial, connection type. Each row has
  a 🪞 Mirror button that calls `MirrorService.start(serial)`. ADB
  environment summary at the top: binary path, devices detected,
  authorized count.
- **Stream (`stream_page`)** — RTMP push to external ingest. Uses a
  separate `RtmpStreamService` (FFmpeg → remote URL, not the local
  TCP server) so the operator can stream to TikTok / YouTube without
  the Android phone in the loop. URL is masked in the UI
  (`rtmp://...stream.example.com/live/****`).
- **Onboarding (`onboarding_page`)** — 5-step wizard: License → Activate
  → Pick device → Bridge → Ready. The state machine in
  `services/onboarding.py` decides which step is current; the page just
  renders + wires actions. First-run users are auto-redirected here
  by `main_window` if `LicenseLifecycleService.current_state()` is None.
- **Device Profiles (`profile_page`)** — CRUD editor over the device
  profile library. Add / edit / delete user profiles; builtins are
  read-only. Live preview of the rotation filter string. Saves go
  through `save_user()` (atomic write) so the editor never corrupts
  the file mid-edit.
- **Backup / Restore (`backup_page`)** — see Phase E2.

### Android receiver (Phase D)

Lives in **its own sibling repo** at
`../npcreate_studio_android/` so the Python and Kotlin sides can ship
independently. The wire-protocol contract is documented in that repo's
README and in the in-tree memory entry
(`memory/reference_android_receiver_repo.md`).

- Package: **`com.npcreate.studio.receiver`** (replaces the legacy
  `com.livemobillrerun.vcam`).
- YUV file path: **`/data/data/com.npcreate.studio.receiver/files/vcam.yuv`**
  — matches `HealthMonitor`'s default `phone_app_package`.
- Files ported: `net/TcpClient` (1 s reconnect back-off), `codec/H264Decoder`
  (async MediaCodec with flush+restart on stall), `io/YuvFileWriter`
  (atomic rename, 16-byte little-endian header), `preview/PreviewBus`
  (single-slot pub/sub), `core/StreamPipeline` (8-second / 16 KiB
  watchdog), `ReceiverService` (foreground service + 6-hour partial
  wake-lock), `MainActivity` (minimal start/stop UI).
- Build: Android Gradle Plugin 8.7.3, Kotlin 2.0.21, minSdk 26,
  targetSdk 34.
- Dropped from v1 (move-to-later phases): Magisk HAL hook, Xposed
  module metadata, TikTok intent broadcasts, loopback YUV reader,
  Live Mode immersive overlay.

### Auto-update orchestrator (Phase E1)

Bridges the existing `UpdateClient` (HTTP fetch + Ed25519 verify) and
`UpdaterService` (byte-level verify + extract) with the three pieces
the refactor was missing:

- **`UpdateOrchestrator`** — daemon poller wrapping
  `UpdateClient.check_latest()`. 30 s startup delay so the rest of the
  app finishes paint + ADB scan before the first network call; default
  poll cadence is 6 hours. Dedups by version string so a stuck CDN
  doesn't re-spam the banner every poll. Every manifest is signature-
  verified before the callback fires.
- **`apply_source_patch(zip_path, *, target_src_dir, sentinel_files)`** —
  atomic `<name>.new` → `<name>.bak` swap. Refuses path traversal,
  refuses zips that don't carry the sentinel files (would brick the
  install), tolerates pre-existing `.bak` directories from prior
  failed attempts.
- **`relaunch()`** — `subprocess.Popen` of `sys.executable -m
  npcreate_studio` then `os._exit(0)`. Uses Popen (not execv) so the
  new process gets a clean PID, working around macOS Tk's "sticky
  widgets after execv" behaviour.
- **Update Center page** — the legacy stub now has a real "ตรวจอัปเดต
  ล่าสุด" button that runs `check_now()` on a worker thread and
  reports back via toast + in-page status pill. Background polling
  shows a toast independently when it sees a new version.

### Backup / restore hardening (Phase E2)

`BackupService` was a 70-line stub in v2.5.0. It's now feature-complete
versus the legacy `vcam-pc/src/backup_restore.py`:

- New `BackupManifest` dataclass embeds `schema` (now **2**), `app_name`,
  `app_version`, `created_at`, `files`. Restore refuses unknown schemas.
- New `list_files()` / `read_manifest()` for UI preview: the customer
  sees "3 files from v2.4.0 on 2026-05-11" before clicking Restore.
- New `suggest_filename()` returns `npcreate-backup-v<version>-<ts>.zip`
  with version-char sanitization so an exotic build tag can't escape
  into a filesystem path.
- README.txt embedded inside the ZIP with end-user restore instructions.
- Restore drops forbidden filenames (`.private_key`, `tokens`, …) at
  **any** depth — not just at the archive root. Path-traversal entries
  are dropped via `is_safe_archive_member`.
- Restore falls back to `copy + unlink` when `os.replace` can't cross
  filesystems (TMPDIR on a different mount than `app_data_dir`).
- The new **Backup / Restore page** sits between "อัปเดตโปรแกรม" and
  "ข่าวสาร" in the sidebar. Create on a worker thread → preview
  manifest of any selected ZIP → confirm restore on a worker thread.

### Service-bundle assembly

`MainWindow.build_services()` is extracted to a module-level helper
(`from npcreate_studio.ui.main_window import build_services`) so the
service wiring can be unit-tested headless. Pages now receive the
bundle as a `services: dict[str, Any]` parameter and pull what they
need (with a fallback for legacy 3-arg signatures during the
migration). New entries in v2.6.0:

```
adb_service, media_service, orchestrator, health_monitor,
device_profile_lib, tiktok_automation, mirror_service, rtmp_service,
update_orchestrator, backup_service, toast, settings
```

The orchestrator only materializes when both `license_server_url` and
`vendor_public_key_hex` are configured; otherwise the Update Center
button stays disabled. Background polling starts on app launch and
stops cleanly on `WM_DELETE_WINDOW`.

### Settings + toolchain

- `settings.stream_host` and `settings.stream_port` (default
  `127.0.0.1:8888`). The legacy default was `0.0.0.0`; the refactor
  rejects non-localhost binds in production via a field validator.
- `MediaService.build_pipe_args()` produces the `ffmpeg -i … -c:v
  libx264 … -f h264 pipe:1` argv that the streaming subprocess feeds
  into the 1-client TCP server.
- `AdbService.exec_argv()` is now public so other services (mirror,
  TikTok automation) compose `adb -s <serial> shell …` without
  reaching into private attributes.

### Memory + repo cross-links

Added a persistent memory entry pointing at the Android sibling repo +
the YUV-file wire-protocol contract
(`memory/reference_android_receiver_repo.md`). Future sessions know
the protocol invariants without re-reading the legacy code.

---

## Upgrade notes

### File layout

The refactor now stores portable state under `settings.app_data_path`:

```
<app_data_path>/
  device_profiles.json     # user-edited profiles (saved by profile_page)
  client_state.json        # last-selected video, window position
  tokens.enc               # encrypted activation tokens (SecureStore)
  master.key               # Fernet key (will move to DPAPI eventually)
  npcreate_studio.sqlite3  # local DB
```

`BackupService` only bundles `device_profiles.json` and
`client_state.json` — activation tokens are intentionally excluded
because they're machine-bound (`SecureStore` encrypts with a Fernet
key derived from the local machine).

### Android receiver

The receiver is a **separate repo** at `../npcreate_studio_android/`.
First-time setup:

```bash
cd ../npcreate_studio_android
./gradlew :app:assembleDebug
./gradlew :app:installDebug   # connected device
```

The PC client's onboarding wizard handles `adb reverse tcp:8888
tcp:8888` automatically. The Android app's package and YUV path are
hard-coded in this Python repo at:

- `services/health_monitor.py` — `phone_app_package` default
- `services/health_monitor.py` — `vcam.yuv` candidate paths

If you ever change the Android package, update those two constants in
lockstep.

### New environment variables / settings

No new envs in v2.6.0. The existing v2.5.0 envs continue to drive the
new code:

- `NPCREATE_LICENSE_SERVER_URL` — enables `UpdateClient` and therefore
  the auto-update poller.
- `NPCREATE_VENDOR_PUBLIC_KEY_HEX` — required for signature verification
  on every update manifest. Missing key → orchestrator is `None` and
  the Update Center button stays disabled.
- `NPCREATE_STREAM_HOST` (default `127.0.0.1`) — bind address for the
  1-client TCP server. Rejected when not localhost / `::1` in
  production.
- `NPCREATE_STREAM_PORT` (default `8888`) — must match the Android
  receiver's `ReceiverService.DEFAULT_PORT`.

### Vendor toolchain

Streaming requires `ffmpeg` and ADB requires the `adb` binary. In dev
the code falls back to `shutil.which()` for both. Production builds
should populate `vendor/<platform>/` and reference them via
`tools_manifest.json` — the manifest's SHA256 is verified before any
subprocess executes.

For RTMP push and scrcpy mirror, add to `vendor/<platform>/`:

- `ffmpeg` (already required for streaming)
- `scrcpy` — Mirror buttons are disabled when this binary is not
  resolvable; the page surfaces the disabled state.

---

## Known limits (carried forward from v2.5.0)

These all require external resources and have not changed since v2.5.0:

- **P0 #6 — Payment merchant verification.** Adapters unit-tested with
  synthetic HMAC; live sandbox accounts still needed.
- **P0 #7 — Windows installer + code-signing.** Build scripts ready,
  real OV/EV certificate still required.
- **P1 #4 — Windows DPAPI for client secret storage.** `SecureStore`
  still uses Fernet + `app_data_dir/master.key`.
- **P1 #7 — Backup / restore drill.** The new `BackupService` covers
  the customer-portable side; the server-side Postgres backup drill is
  out of scope for the client release.

### New in v2.6.0 (legacy parity gaps not yet ported)

- **Magisk HAL hook** for the Android receiver. The receiver writes the
  YUV file correctly, but the legacy could plug that file in as the
  system camera via a Magisk module. Tracked for a future Android-side
  phase.
- **Xposed module + TikTok intent broadcasts.** Same story as the HAL
  hook — wire protocol is preserved, the integration glue isn't ported.
- **Loopback YUV preview** in the Android app. The current
  `MainActivity` only shows status + frame counter; the legacy could
  preview frames in-app. Not on the path to feature parity for the PC
  client.

---

## Test growth

```
v2.4.0 baseline:         ~22 tests
v2.5.0 (server hardening): 152 tests, +4 Postgres integration
v2.6.0 (client features): 416 tests, +4 Postgres integration
```

Coverage of new services:

| Module                            | Tests |
|-----------------------------------|------:|
| Streaming subprocess + server     |    14 |
| ADB service                       |     8 |
| Health monitor                    |    10 |
| Device profiles + repository      |    22 |
| TikTok automation                 |    16 |
| Mirror service                    |    12 |
| Live / Devices / RTMP views       |    24 |
| Onboarding state machine          |    16 |
| Profile-page validators           |    18 |
| RTMP stream service               |    14 |
| Update orchestrator + apply       |    22 |
| Backup service                    |    19 |
| Service-bundle assembly           |     8 |

All run on Python 3.11 / 3.12 / 3.13 in CI. Long-running threads in
`TikTokAutomation`, `MirrorService`, `StreamPipeline`, `RtmpStreamService`,
`HealthMonitor`, and `UpdateOrchestrator` are daemonized and join with
a 2-second timeout on stop, so the test process always exits cleanly.

---

## Acknowledgements

Phases A1–E2 were built collaboratively with Claude Opus 4.7 (1M
context) across two long sessions. See `git log` for per-commit
attribution and the per-phase commit messages for design notes.
