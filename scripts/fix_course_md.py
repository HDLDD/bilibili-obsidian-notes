#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repair the two Markdown defects that recur in generated course notes.

  --links   rewrite [[../02-标题|别名]] into [[<讲在库里的路径>/02-标题|别名]]
            (Obsidian wikilinks do not support relative paths at all, so these
            look fine in a text editor and break in the app)
  --pipes   inside table rows, turn \\left| / \\right| / \\big| into \\lvert / \\rvert
            (a bare | splits the cell even inside $...$)

Both are idempotent and print every file they touch.

  python fix_course_md.py --vault "<vault>/<course>" --manifest work/manifest.json --links --pipes
"""
import argparse
import io
import json
import os
import re

PIPE_SUBS = [
    (re.compile(r"\\left\s*\|"), r"\\lvert "),
    (re.compile(r"\\right\s*\|"), r"\\rvert "),
    (re.compile(r"\\(?:bigl|Bigl|biggl|Biggl)\s*\|"), r"\\lvert "),
    (re.compile(r"\\(?:big|Big|bigg|Bigg)\s*\|"), r"\\lvert "),
]


def read(p):
    return io.open(p, encoding="utf-8", newline="").read()


def write(p, s):
    io.open(p, "w", encoding="utf-8", newline="").write(s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--links", action="store_true")
    ap.add_argument("--pipes", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not (a.links or a.pipes):
        a.links = a.pipes = True
    rows = json.loads(read(a.manifest))
    touched = 0
    for r in rows:
        lp = os.path.join(a.vault, *r["lesson_path"].split("/"))
        if not os.path.isdir(lp):
            continue
        for f in sorted(os.listdir(lp)):
            if not f.endswith(".md"):
                continue
            p = os.path.join(lp, f)
            s = read(p)
            orig = s

            if a.links:
                def repl(m):
                    inner = m.group(1)
                    target, _, alias = inner.partition("|")
                    bare = re.sub(r"^\.\./|^\./", "", target.strip())
                    full = f"{r['lesson_path']}/{bare}"
                    return f"[[{full}|{alias}]]" if alias else f"[[{full}]]"

                s = re.sub(r"\[\[(\.\./[^\]]+)\]\]", repl, s)
                s = re.sub(r"\[\[(\./[^\]]+)\]\]", repl, s)

            if a.pipes:
                out = []
                for line in s.split("\n"):
                    if line.strip().startswith("|"):
                        for pat, rep in PIPE_SUBS:
                            line = pat.sub(rep, line)
                        # [[target|alias]] splits the cell unless the bar is escaped;
                        # the lookbehind keeps already-escaped [[t\|a]] untouched
                        line = re.sub(r"\[\[([^|\]]+)(?<!\\)\|([^|\]]+)\]\]", r"[[\1\\|\2]]", line)
                    out.append(line)
                s = "\n".join(out)

            if s != orig:
                n = sum(1 for x, y in zip(orig.split("\n"), s.split("\n")) if x != y)
                print(f"{'would fix' if a.dry_run else 'fixed'} {os.path.relpath(p, a.vault)} ({n} lines)")
                if not a.dry_run:
                    write(p, s)
                touched += 1
    print("files touched:", touched)


if __name__ == "__main__":
    main()
