#!/usr/bin/env python3
"""Check Obsidian Markdown links, wikilinks and heading anchors."""
import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FENCE_RE = re.compile(r"```.*?```", re.S)
MD_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
WIKI_RE = re.compile(r"\[\[([^\]]+)\]\]")


def normalize_heading(text: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = text.replace("**", "").replace("*", "").replace("_", "")
    return re.sub(r"\s+", " ", text).strip()


def get_headings(text: str) -> set[str]:
    return {
        normalize_heading(m.group(2))
        for m in re.finditer(r"^(#{1,6})\s+(.+)$", text, re.M)
    }


def build_stem_index(vault: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    for path in vault.rglob("*.md"):
        if ".obsidian" in path.parts or ".trash" in path.parts:
            continue
        index.setdefault(path.stem, []).append(path)
    return index


def resolve_wiki(
    target: str,
    note: Path,
    vault: Path,
    stem_index: dict[str, list[Path]],
) -> tuple[Path | None, str | None]:
    base, _, heading = target.partition("#")
    base = base.strip()
    heading = heading.strip() or None
    if not base:
        return note, heading

    raw = Path(base)
    if base.startswith("../") or base.startswith("./"):
        # Obsidian resolves [[...]] by vault path or by unique file name; a relative
        # "../x" is never a valid wikilink target, even though the bare name exists
        # next door. Reporting it as OK here was a real false negative.
        return None, heading
    candidates = []
    for root in (vault, note.parent):
        candidate = root / raw
        if candidate.suffix != ".md":
            candidate = candidate.with_suffix(".md")
        candidates.append(candidate)
    if raw.suffix == "":
        candidates.extend(stem_index.get(raw.name, []))

    for candidate in candidates:
        if candidate.exists():
            return candidate, heading
    return None, heading


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", required=True, help="Obsidian vault or course folder")
    args = parser.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        raise SystemExit(f"Vault not found: {vault}")

    stem_index = build_stem_index(vault)
    notes = sorted(p for p in vault.rglob("*.md") if ".obsidian" not in p.parts)
    misses = 0

    for note in notes:
        text = note.read_text(encoding="utf-8", errors="replace")
        scan_text = FENCE_RE.sub("", text)
        headings = get_headings(text)
        print(f"\n== {note.relative_to(vault)} ==")

        for raw_target in MD_LINK_RE.findall(scan_text):
            target = raw_target.strip().strip("<>")
            if target.startswith(("http://", "https://", "mailto:", "data:", "#")):
                continue
            target = unquote(target.split("#", 1)[0])
            if not target:
                continue
            candidate = Path(target)
            if not candidate.is_absolute():
                candidate = (note.parent / candidate).resolve()
            ok = candidate.exists()
            misses += 0 if ok else 1
            print(("OK   " if ok else "MISS ") + f"file: {target}")

        for raw_target in WIKI_RE.findall(scan_text):
            target = raw_target.split("|", 1)[0].strip()
            resolved, heading = resolve_wiki(target, note, vault, stem_index)
            if resolved is None:
                misses += 1
                print(f"MISS wiki: {target}")
                continue
            if heading:
                target_text = resolved.read_text(encoding="utf-8", errors="replace")
                if normalize_heading(heading) not in get_headings(target_text):
                    misses += 1
                    print(f"MISS heading: [[{target}]]")
                    continue
            print(f"OK   wiki: {target}")

    print(f"\nChecked {len(notes)} note(s); misses={misses}")
    return 1 if misses else 0


if __name__ == "__main__":
    raise SystemExit(main())
