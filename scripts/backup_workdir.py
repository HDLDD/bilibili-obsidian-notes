#!/usr/bin/env python3
"""Create and verify a timestamped zip backup of a work directory."""
import argparse
import hashlib
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--backup-dir", default=None)
    args = parser.parse_args()

    workdir = Path(args.workdir).expanduser().resolve()
    if not workdir.is_dir():
        raise SystemExit(f"Work directory not found: {workdir}")

    backup_dir = (
        Path(args.backup_dir).expanduser().resolve()
        if args.backup_dir
        else workdir.parent / "_backups"
    )
    backup_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = backup_dir / f"{workdir.name}_{stamp}"
    archive = Path(
        shutil.make_archive(str(base), "zip", root_dir=str(workdir.parent), base_dir=workdir.name)
    )

    with zipfile.ZipFile(archive) as zf:
        bad = zf.testzip()
        if bad:
            raise SystemExit(f"Backup verification failed at: {bad}")
        count = len(zf.namelist())

    manifest = backup_dir / f"{workdir.name}_{stamp}_sha256.txt"
    lines = []
    for path in sorted(workdir.rglob("*")):
        if path.is_file():
            lines.append(f"{sha256(path)}  {path.relative_to(workdir)}")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"backup={archive}")
    print(f"files={count} size={archive.stat().st_size}")
    print(f"manifest={manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
