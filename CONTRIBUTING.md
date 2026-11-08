# Contributing to trackai

Notes for building, testing and releasing trackai. Design rules and invariants
live in [AGENTS.md](AGENTS.md); read it before changing a provider or the
installer.

## Branches

- **`main`**: the macOS app, and where both installers start.
- **`linux-gtk`**: the Linux GTK app, until it is merged into `main`.

`install.sh` sends each OS to its branch, so users only ever run the `main`
URL or `trackai update`. To test another branch or tag, set `TRACKAI_REF`:

```sh
curl -fsSL https://raw.githubusercontent.com/sjcsoftware/trackai/<ref>/install.sh | TRACKAI_REF=<ref> bash
```

An explicit ref never falls back to a different release.

## Build and run from source

```sh
git clone https://github.com/sjcsoftware/trackai
cd trackai
./install.sh                 # installs from this checkout for your OS, no downloads
```

### macOS

Requires the Xcode Command Line Tools.

```sh
./scripts/build.sh <version>                   # universal dist/TrackAI.app + dist/TrackAI.zip
./trackai                                      # run the built app
./trackai --render out.png [--detailed|--settings]
```

If the default SDK lacks the SwiftUI macro plugin, build against the 26.x SDK:
`SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk ./scripts/build.sh <version>`.

### Linux

Needs Python 3.8+ with `python3-gi`, `python3-gi-cairo`, `python3-cairo` and `gir1.2-gtk-3.0`.

```sh
./linux/bin/trackai stats --offline
./linux/bin/trackai start
./linux/scripts/build.sh                               # tests + dist/trackai-linux.tar.gz
python3 -m unittest discover -s linux/tests -v         # standard library only
/usr/bin/python3 linux/scripts/smoke-ui.py /tmp/trackai-preview   # GTK screenshots
```

The smoke check uses synthetic data. On a headless runner, prefix it with
`xvfb-run -a`. `TRACKAI_HOME` overrides the Python package directory and
`TRACKAI_PYTHON` the interpreter; GTK must be available to that interpreter.

## Payloads

Both payloads are committed under `dist/` because the installer downloads them
from the branch:

- Rebuild `dist/trackai-linux.tar.gz` with `linux/scripts/build.sh` after any
  change to Linux sources, `linux/bin/trackai`, `install.sh` or `README.md`
  (they are packaged). CI fails if it is stale.
- Changes to `bin/trackai` need a rebuilt `dist/TrackAI.zip` on macOS, because
  that launcher is embedded in the signed app bundle.

## Releases

- macOS releases are tagged on `main` and ship `TrackAI.zip` and `trackai-linux.tar.gz`.
- Linux releases are tagged on `linux-gtk` and ship only `trackai-linux.tar.gz`.
- Release notes tell users to run `trackai update`.

## Adding a provider

- **macOS:** implement `UsageProvider`, add a `ProviderKind` case and a
  `ProviderMark` glyph, and register it in `ProviderRegistry.all`.
- **Linux:** implement a provider that returns `ProviderSnapshot` objects, add
  it to `PROVIDERS` in `linux/src/trackai/providers.py`, add its outline to
  `linux/src/trackai/provider_mark.py`, and include its key in the settings
  defaults.

The panels and settings read the registry, so no view needs a per-provider
branch.

## Data sources

| | Claude Code | Codex |
| --- | --- | --- |
| Login | `~/.claude/.credentials.json`, Keychain (macOS, via `security`) or `secret-tool` (Linux) | `~/.codex/auth.json` |
| Tokens | `~/.claude/projects/**/*.jsonl` | `~/.codex/sessions/**/*.jsonl` |
| Plan limits | Anthropic's OAuth usage endpoint (5-minute floor, 429 back-off) | `rate_limits` snapshots in the rollout logs (no network) |

`CLAUDE_CONFIG_DIR` and `CODEX_HOME` are respected. Costs use API prices and
are estimates.
