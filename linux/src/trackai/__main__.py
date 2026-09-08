"""Headless CLI flags share the same providers and rate-limit cache as GTK."""
import argparse
import json
import sys
from datetime import timezone
from . import __version__
from .providers import PROVIDERS, collect
from .settings import Settings


def iso(date):
    return date.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if date else None


def serialize(data):
    local = data.local
    return {
        "provider": data.kind, "name": data.name, "email": data.account.email,
        "configDir": data.account.config_dir, "status": data.credential_status,
        "plan": data.subscription_type, "planDetail": data.rate_limit_tier,
        "limitsError": data.api_error,
        "limitsFetchedAt": iso(data.api.fetched_at) if data.api else None,
        "limits": [{"name": l.display_name, "kind": l.kind, "percent": l.percent,
                    "resetsAt": iso(l.resets_at)} for l in data.api.limits] if data.api else [],
        "local": {"today": local.today.to_dict(), "last5h": local.last5h.to_dict(),
                  "last7d": local.last7d.to_dict(), "last30d": local.last30d.to_dict(),
                  "allTime": local.all_time.to_dict(),
                  "byModel": [{"model": m.model, "stats": m.totals.to_dict()} for m in local.per_model],
                  "byModel30d": [{"model": m.model, "stats": m.totals.to_dict()} for m in local.per_model_30d]},
    }


def gather_cli(offline=False):
    return collect({p.kind: p() for p in PROVIDERS}, Settings.shared().snapshot(), offline=offline)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Claude Code and Codex usage in your Linux system tray")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--stats", action="store_true", help="print usage as JSON; no display needed")
    modes.add_argument("--setup", action="store_true", help="check existing CLI logins")
    parser.add_argument("--offline", action="store_true", help="local data only; skip Claude's usage endpoint")
    parser.add_argument("--version", action="version", version="trackai " + __version__)
    args = parser.parse_args(argv)
    if args.stats or args.setup:
        data = gather_cli(args.offline)
        if args.stats:
            print(json.dumps({"providers": [serialize(d) for d in data]}, indent=2, ensure_ascii=False))
            return 0
        print("trackai setup\n=============")
        for item in data:
            print("{}: {}{}".format(item.name, item.credential_status,
                                  " (" + item.subscription_type + ")" if item.subscription_type else ""))
            if item.api_error:
                print("  " + item.api_error)
        if any(d.credential_status == "ok" for d in data):
            print("Connected. Run `trackai start` to open the tray app.")
            return 0
        print("Run `claude` and/or `codex` in a terminal, log in, then run `trackai setup` again.")
        return 1
    try:
        from .app import run
    except (ImportError, ValueError) as err:
        sys.stderr.write("trackai: GTK bindings unavailable ({}). Re-run install.sh or install\n"
                         "python3-gi python3-gi-cairo python3-cairo gir1.2-gtk-3.0 "
                         "gir1.2-ayatanaappindicator3-0.1.\n".format(err))
        return 1
    return run()


if __name__ == "__main__":
    sys.exit(main())
