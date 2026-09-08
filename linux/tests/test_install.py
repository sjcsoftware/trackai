"""Installer/CLI integration with isolated homes and mocked downloads (no network/apt)."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="trackai-install-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home with spaces"
        self.home.mkdir()
        self.shims = self.root / "shims"
        self.shims.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), XDG_DATA_HOME=str(self.home / "data"),
                        XDG_CONFIG_HOME=str(self.home / "config"), XDG_CACHE_HOME=str(self.home / "cache"),
                        CLAUDE_CONFIG_DIR=str(self.home / "claude"), CODEX_HOME=str(self.home / "codex"),
                        PATH=str(self.shims) + ":/usr/bin:/bin", XDG_CURRENT_DESKTOP="", DISPLAY="", WAYLAND_DISPLAY="")
        for key in ("TRACKAI_HOME", "TRACKAI_REF", "TRACKAI_CLI"):
            self.env.pop(key, None)
        # Core tests run without GTK; dependency probes succeed but actual Python
        # execution remains real. No apt or network can run from these tests.
        py = self.shims / "test-python"
        py.write_text('#!/bin/bash\nif [ "${1:-}" = "-c" ]; then exit 0; fi\nexec ' + shutil.which("python3") + ' "$@"\n')
        py.chmod(0o755)
        self.env["TRACKAI_PYTHON"] = str(py)
        self.shim("uname", 'echo "${TEST_OS:-Linux}"')
        self.shim("apt-get", 'echo "unexpected apt" >&2; exit 99')
        self.shim("sudo", 'echo "unexpected sudo" >&2; exit 99')
        self.shim("secret-tool", 'exit 1')
        self.shim("trackai", 'exit 0')
        self.shim("curl", 'echo "$*" >> "$TEST_URLS"\n[ "${FAIL_DOWNLOAD:-}" != "1" ] || exit 22\nwhile [ "$#" -gt 0 ]; do if [ "$1" = "-o" ]; then cp "$TEST_PAYLOAD" "$2"; exit; fi; shift; done\nexit 1')
        self.env["TEST_URLS"] = str(self.root / "urls")
        payload = self.root / "payload.tar.gz"
        with tarfile.open(payload, "w:gz") as archive:
            for directory in ("linux/src/trackai", "linux/bin", "linux/packaging", "linux/scripts"):
                archive.add(ROOT / directory, arcname="trackai-linux/" + directory)
        self.env["TEST_PAYLOAD"] = str(payload)

    def shim(self, name, body):
        path = self.shims / name
        path.write_text("#!/bin/bash\n" + body + "\n")
        path.chmod(0o755)

    def install(self, checkout=False):
        args = ["bash", str(ROOT / "install.sh")] if checkout else ["bash"]
        return subprocess.run(args, input=None if checkout else (ROOT / "install.sh").read_text(),
                              text=True, capture_output=True, env=self.env, cwd=self.root, timeout=30)

    def cli(self, *args):
        return subprocess.run([str(self.home / ".local/bin/trackai"), *args],
                              text=True, capture_output=True, env=self.env, cwd=self.root, timeout=15)

    def test_piped_installer_detects_linux_and_installed_cli_is_headless(self):
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        urls = Path(self.env["TEST_URLS"]).read_text()
        self.assertIn("/main/dist/trackai-linux.tar.gz", urls)
        self.assertNotIn("TrackAI.zip", urls)
        desktop = (self.home / "data/applications/trackai.desktop").read_text()
        self.assertIn('Exec="' + str(self.home / ".local/bin/trackai") + '" start', desktop)
        stats = self.cli("stats", "--offline")
        self.assertEqual(stats.returncode, 0, stats.stderr)
        self.assertEqual(json.loads(stats.stdout), {"providers": []})
        self.assertNotEqual(self.cli("start").returncode, 0)
        self.assertNotEqual(self.cli("unknown-command").returncode, 0)
        self.assertNotEqual(self.cli("setup", "--offline").returncode, 0)
        self.assertEqual(self.cli("uninstall").returncode, 0)
        self.assertFalse((self.home / "data/trackai").exists())
        self.assertFalse((self.home / ".local/bin/trackai").exists())

    def test_checkout_never_downloads(self):
        result = self.install(checkout=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(Path(self.env["TEST_URLS"]).exists())

    def test_explicit_ref_is_respected(self):
        self.env["TRACKAI_REF"] = "linux-support"
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("/linux-support/dist/trackai-linux.tar.gz", Path(self.env["TEST_URLS"]).read_text())

    def test_download_failure_preserves_existing_installation(self):
        dest = self.home / "data/trackai"
        dest.mkdir(parents=True)
        (dest / "keep").write_text("installed")
        self.env["FAIL_DOWNLOAD"] = "1"
        self.assertNotEqual(self.install().returncode, 0)
        self.assertEqual((dest / "keep").read_text(), "installed")

    def test_macos_selects_mac_archive_before_installation(self):
        self.env.update(TEST_OS="Darwin", FAIL_DOWNLOAD="1")
        self.assertNotEqual(self.install().returncode, 0)
        self.assertIn("/main/dist/TrackAI.zip", Path(self.env["TEST_URLS"]).read_text())

    def test_unsupported_os_does_not_download(self):
        self.env["TEST_OS"] = "FreeBSD"
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("macOS and Linux only", result.stderr)
        self.assertFalse(Path(self.env["TEST_URLS"]).exists())

    def test_pid_file_cannot_signal_unrelated_process(self):
        self.assertEqual(self.install().returncode, 0)
        self.env["TRACKAI_PYTHON"] = shutil.which("python3")
        pid = self.home / "cache/trackai/trackai.pid"
        pid.parent.mkdir(parents=True, exist_ok=True)
        pid.write_text(str(os.getpid()))
        self.assertIn("not running", self.cli("status").stdout)
        self.assertEqual(self.cli("stop").returncode, 0)
        os.kill(os.getpid(), 0)


if __name__ == "__main__":
    unittest.main()
