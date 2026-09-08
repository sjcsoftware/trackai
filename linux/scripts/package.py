"""Reproducible source archive. Exclude caches, tests, and unrelated Mac payloads."""
import gzip
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
files = [ROOT / name for name in ("README.md", "LICENSE", "install.sh")]
for name in ("linux/src", "linux/bin", "linux/scripts", "linux/packaging"):
    files.extend(p for p in (ROOT / name).rglob("*") if p.is_file()
                 and "__pycache__" not in p.parts and p.suffix != ".pyc")
(ROOT / "dist").mkdir(exist_ok=True)
with (ROOT / "dist/trackai-linux.tar.gz").open("wb") as raw:
    with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w") as archive:
            for path in sorted(files):
                info = tarfile.TarInfo("trackai-linux/" + path.relative_to(ROOT).as_posix())
                data = path.read_bytes()
                info.size, info.mtime = len(data), 0
                info.mode = 0o755 if path.suffix == ".sh" or path.name == "trackai" else 0o644
                archive.addfile(info, io.BytesIO(data))
