# trackai

Claude Code + Codex usage monitor for the macOS menu bar. Native Swift/SwiftUI,
macOS 13+, universal binary, MIT, © 2026 Cha Seungjoon.

Baseline this grew out of: `sjcsoftware/trackclaude` (single-provider, macOS + Linux).
trackai is macOS only and multi-provider.

## Layout

```
Package.swift                 SwiftPM executable, one target
Sources/trackai/
  main.swift                  CLI modes (--setup/--stats/--render/--version) then NSApp
  AppDelegate.swift           status item, borderless NSPanel, settings window
  AppState.swift              refresh loop, snapshots keyed by ProviderKind, menu bar maths
  Settings.swift              UserDefaults-backed prefs + onMain() helper
  StatusIcon.swift            menu bar dial / provider glyph
  ProviderMark.swift          vector logos (no image assets in the repo)
  Formatting.swift            token/USD/relative-time strings, ISO date parsing
  Providers/
    Provider.swift            UsageEntry, TokenTotals, LocalStats, LimitInfo,
                              ProviderSnapshot, UsageProvider, ProviderRegistry
    ClaudeProvider.swift      local scan + Anthropic OAuth usage endpoint
    CodexProvider.swift       local scan only (limits come from the rollout log)
  Claude/                     credentials, usage API, transcript scanner, pricing
  Codex/                      credentials (JWT claims), session scanner, pricing
  Views/                      Components, ProviderBoxes, PanelView, SettingsView
bin/trackai                   user-facing CLI (setup/start/stop/stats/update/uninstall)
install.sh                    curl | bash installer; also works from a checkout
scripts/build.sh              universal build → dist/TrackAI.app + .zip + ./trackai
scripts/gen-icon.swift        renders the .iconset
dist/TrackAI.zip              the payload install.sh downloads
```

## Invariants

1. **No pasted tokens, ever.** Both providers are read from the state the CLIs
   already keep on disk (and the Keychain for Claude). If a change would make a
   user copy a credential, it is the wrong change.
2. **The app bundle embeds `bin/trackai` as `Contents/Resources/trackai-cli`,**
   and the installer takes the CLI from there when not running from a checkout.
   Any edit to `bin/trackai` therefore requires rebuilding `dist/TrackAI.zip`.
3. **Codex makes no network call.** Its rate limits come from the `rate_limits`
   block in `~/.codex/sessions/**/*.jsonl`. If that snapshot is stale the UI says
   so; it must never be silently presented as live.
4. **Claude's usage endpoint is rate-limited hard.** Keep the 5-minute freshness
   floor, the 1-minute manual-refresh floor, the persisted cache and the
   exponential 429 back-off in `ClaudeProvider`.
5. **Provider scans run off-main.** Read `Settings.shared` through `onMain {}`
   from a provider, never directly.
6. **Adding a provider** should only mean: a `UsageProvider` conformance, a
   `ProviderKind` case, a `ProviderMark` glyph, and a `ProviderRegistry` entry.
   Nothing in the views or settings should need a per-provider branch beyond
   copy. Keep it that way.

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
