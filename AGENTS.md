# trackai

Claude Code + Codex usage monitor for the macOS menu bar and Linux system tray.
Swift/SwiftUI on macOS 13+ (universal); Python/GTK 3 on Linux (Ubuntu 22.04+).
MIT, © 2026 Cha Seungjoon.

Baseline this grew out of: `sjcsoftware/trackclaude` (single-provider, macOS + Linux).
trackai supports both platforms and multiple providers.

## Layout

```
Package.swift                 SwiftPM executable, one target
Sources/trackai/
  main.swift                  CLI modes (--setup/--stats/--render/--version) then NSApp
  AppDelegate.swift           status item, borderless NSPanel, settings window
  AppState.swift              refresh loop, snapshots keyed by ProviderKind, menu bar maths
  Settings.swift              UserDefaults-backed prefs + onMain() helper
  StatusIcon.swift            menu bar bolt meter / provider glyph
  ProviderMark.swift          official provider marks as SVG outlines (no image assets)
  Formatting.swift            token/USD/relative-time strings, ISO date parsing
  Providers/
    Provider.swift            UsageEntry, TokenTotals, LocalStats, LimitInfo,
                              ProviderSnapshot, UsageProvider, ProviderRegistry
    ClaudeProvider.swift      local scan + Anthropic OAuth usage endpoint
    CodexProvider.swift       local scan only (limits come from the rollout log)
  Claude/                     credentials, usage API, transcript scanner, pricing
  Codex/                      credentials (JWT claims), session scanner, pricing
  Views/                      Components, ProviderBoxes, PanelView, SettingsView
linux/src/trackai/           GTK app, provider registry, scanners, settings
linux/src/trackai/provider_mark.py  same outlines drawn with cairo
linux/src/trackai/sni.py      StatusNotifierItem served over Gio D-Bus (no libappindicator)
linux/src/trackai/popup.py    override-redirect panel + seat grab; x11.py finds the bar rect
linux/src/trackai/style.py    palette/CSS from the GTK theme accent
linux/bin/trackai             Linux CLI (separate from signed Mac bundle)
linux/scripts/build.sh        tests + reproducible Linux source archive
linux/scripts/smoke-ui.py     GTK checks and screenshots using synthetic data
linux/tests/                 headless accounting/cache/installer tests
bin/trackai                   macOS CLI (setup/start/stop/stats/update/uninstall)
install.sh                    curl | bash installer; also works from a checkout
scripts/build.sh              universal build → dist/TrackAI.app + .zip + ./trackai
scripts/gen-icon.swift        renders the .iconset
dist/TrackAI.zip              macOS payload
dist/trackai-linux.tar.gz     Linux payload; installer selects by uname
```

## Invariants

1. **No pasted tokens, ever.** Both providers are read from the state the CLIs
   already keep on disk (and the Keychain for Claude). If a change would make a
   user copy a credential, it is the wrong change.
2. **The app bundle embeds `bin/trackai` as `Contents/Resources/trackai-cli`,**
   and the installer takes the CLI from there when not running from a checkout.
   Any edit to `bin/trackai` therefore requires rebuilding `dist/TrackAI.zip`
   on macOS. The Linux launcher is `linux/bin/trackai`; rebuild its source
   archive with `linux/scripts/build.sh` after Linux or packaged-doc changes.
3. **Codex makes no network call.** Its rate limits come from the `rate_limits`
   block in `~/.codex/sessions/**/*.jsonl`. If that snapshot is stale the UI says
   so; it must never be silently presented as live.
4. **Claude's usage endpoint is rate-limited hard.** Keep the 5-minute freshness
   floor, the 1-minute manual-refresh floor, the persisted cache and the
   exponential 429 back-off in `ClaudeProvider`.
5. **Provider scans run off-main.** Read `Settings.shared` through `onMain {}`
   from a provider, never directly. Linux captures `Settings.snapshot()` on the
   GTK thread, scans on a worker, and publishes via `GLib.idle_add`.
6. **Adding a provider** should only mean: a `UsageProvider` conformance, a
   `ProviderKind` case, a `ProviderMark` glyph, and a `ProviderRegistry` entry.
   Nothing in the views or settings should need a per-provider branch beyond
   copy. Keep it that way.
7. **The Mac app is ad-hoc signed, so a direct Keychain read re-prompts after
   every build.** Claude Code writes `Claude Code-credentials` with
   `/usr/bin/security add-generic-password -U`, which keeps `security` on the
   item's ACL and in its `apple-tool:` partition. "Skip the Keychain password
   prompt" (`claudeSkipKeychainPrompt`, on by default) reads through that tool
   and never shows a dialog. With it off, `ClaudeAuth` first probes with
   `SecKeychainSetUserInteractionAllowed(false)` (the file keychain ignores
   `kSecUseAuthenticationUI`) and floats `KeychainPromptHint` only while the
   real dialog is up. Linux reads files or Secret Service and has no equivalent.

## Data formats relied on

Claude Code transcripts (`~/.claude/projects/**/*.jsonl`): assistant records with
`message.model`, `message.usage.{input_tokens,output_tokens,cache_creation_input_tokens,cache_read_input_tokens}`,
top-level `timestamp` and `requestId`. Deduped by `message.id:requestId`.

Codex rollout logs (`~/.codex/sessions/**/*.jsonl`), two generations:

- Newer: one `token_usage_record` per response, `payload.usage` is that
  response's delta, `payload.response_id` is the dedup key.
- Older: only `event_msg`/`token_count`, where `payload.info.last_token_usage`
  is the delta (`info` is null on the first event of a session).

A file with any `token_usage_record` ignores its `token_count` usage so nothing
is counted twice. `turn_context.model` / `session_meta.model` names the model for
subsequent records. `payload.rate_limits.{primary,secondary}` carry
`used_percent`, `window_minutes` and `resets_at` (epoch seconds); the newest such
block across all sessions wins. Codex's `input_tokens` includes
`cached_input_tokens`, and `output_tokens` includes `reasoning_output_tokens`.

## Antigravity

Deliberately not supported. The Antigravity CLI's OAuth token is readable
(Keychain service `gemini`, account `antigravity`), but there is no usable quota
source behind it: `cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary`
answers `403 SUBSCRIPTION_REQUIRED` for consumer logins, and
`aicode.googleapis.com/v1beta/{parent}:fetchQuotaStatus` (the RPC the CLI actually
uses, `google.cloud.businessaicode.v1main.PredictionService/FetchQuotaStatus`)
is not routed for public HTTP/JSON. Local token counts live in protobuf blobs in
`~/.gemini/antigravity-cli/conversations/*.db` with no documented schema. Revisit
only if Google exposes a quota endpoint that a consumer token can actually call.

## Verification done

- Both providers read correctly on a real machine: Claude Pro (session/weekly
  limits from the API, 195M tokens across Opus 5 + Sonnet 5) and Codex Plus
  (5h/weekly from the rollout log, both rollout-log generations parsed).
- `--render` output checked for the overview page, the detailed page and the
  settings window.
- Universal binary builds for arm64 + x86_64; the app bundle launches and holds
  a status item.
- Provider marks are the official Claude and Codex SVGs, normalised to absolute
  M/L/C/Z commands on a 24x24 viewBox. Keep the Swift and Python copies identical.
- Command Line Tools whose default SDK is macOS 27 lack the SwiftUI `@State`
  macro plugin, so the build fails. Build against the 26.x SDK:
  `SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk ./scripts/build.sh <version>`.

## Branches and releases

11. **Linux ships from `linux-gtk`, macOS from `main`,** until `linux-gtk` is
    merged. `install.sh` sets `MACOS_REF`, `LINUX_REF` and `THIS_REF` (the
    branch that copy is committed on, so it is the one line that differs
    between the branches). Without `TRACKAI_REF`, an installer on the wrong
    branch for this OS downloads the right branch's `install.sh` and runs it
    with `TRACKAI_REF` set, so the install steps always match the payload.
    Both CLIs' `update` fetch `main/install.sh`, so plain `trackai update`
    lands on the right branch everywhere. When merging, set `LINUX_REF="main"`
    and keep `THIS_REF` per branch. Linux releases are tagged on `linux-gtk`
    and ship only `trackai-linux.tar.gz`; release notes say plain
    `trackai update`.

## Linux tray

8. **Linux serves its own StatusNotifierItem.** libappindicator marks items
   menu-only, so hosts open a menu on click; ours sets `ItemIsMenu=false` and
   handles `Activate(x, y)` by opening the panel there. There is no hover:
   `Title` and `ToolTip` stay empty (hosts render them as tooltips, and they
   could not keep up with live numbers). Re-register whenever
   `org.kde.StatusNotifierWatcher` reappears (bars restart). With no watcher
   on X11, fall back to `Gtk.StatusIcon` (XEmbed), also without a tooltip.
9. **The panel is an override-redirect popup on X11** with a pointer+keyboard
   seat grab: only Escape or an outside click closes it. Placement uses the
   rect of the top-level window under the click (the bar), because i3 and many
   bars set no `_NET_WORKAREA`/struts. Wayland keeps an undecorated top-level.
   Never style per desktop: colours come from the GTK theme accent.
10. **Codex has no daily limit.** Its snapshots set `has_daily = False`: no
    Daily row in the panel, and the "daily" icon metric reads its 5h limit.

## Linux verification

- Run `python3 -m unittest discover -s linux/tests -v` (standard library only).
- Tray end-to-end: Xephyr (parented to an unmapped window) on a private
  `dbus-run-session` with a stub watcher; check registration, `ItemIsMenu`,
  placement under a 46px top bar, Escape / outside-click dismissal, page
  switching, and re-registration after the watcher restarts.
- Run `/usr/bin/python3 linux/scripts/smoke-ui.py /tmp/trackai-preview` with a
  display, or prefix with `xvfb-run -a` in CI. It uses synthetic data only.
- `linux/scripts/build.sh` runs tests and regenerates the committed payload.
- The installer must select the OS automatically through the same `main` URL
  (see invariant 11). `TRACKAI_REF` is an optional developer override; never
  mix it with latest-release fallback downloads from another ref.
- Ubuntu 24.04 local Claude/Codex accounting and GTK windows have been verified.
  Linux never changes CLI credentials. Its Claude cache uses a cross-process
  lock and persists freshness/back-off, including requests from `stats`.
