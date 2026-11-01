#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Renumber knowledge articles inside each lesson folder so `00-` and `99-` stay reserved.

Some writers start their first article at `00-xxx.md`. That collides with `00-本讲索引.md`
in every tool that treats `00-` as the index - including this repo's verifier, which then
silently stops counting the article. This script shifts a lesson's articles to 01..NN and
rewrites filenames, `article:` frontmatter, wikilinks, aliases and index table numbers.

  python renumber_articles.py --vault "<vault>" --manifest "<work>/manifest.json" [--dry-run]
"""
import argparse
import io
import json
import os
import re


def read(p):
    return io.open(p, encoding="utf-8", newline="").read()


def write(p, s):
    io.open(p, "w", encoding="utf-8", newline="").write(s)


def article_files(lp):
    out = []
    for f in sorted(os.listdir(lp)):
        if not re.match(r"^\d{2}-.*\.md$", f):
            continue
        if f in ("00-本讲索引.md", "99-扩展笔记.md"):
            continue
        out.append(f)
    return out


def renumber_lesson(lp, plan):
    """plan: [(old_file, new_file), ...] applied in place."""
    stems = {old[:-3]: new[:-3] for old, new in plan}
    aliases = {f"{old[:2]} {old[3:-3]}": f"{new[:2]} {new[3:-3]}" for old, new in plan}
    numbers = {old[:2]: new[:2] for old, new in plan}
    repl = sorted(list(stems.items()) + list(aliases.items()), key=lambda kv: -len(kv[0]))
    for f in sorted(os.listdir(lp)):
        if not f.endswith(".md"):
            continue
        p = os.path.join(lp, f)
        s = read(p)
        orig = s
        for old, new in repl:
            s = s.replace(old, new)
        s = re.sub(r'(?m)^article:\s*"(\d{2})"',
                   lambda m: 'article: "%s"' % numbers.get(m.group(1), m.group(1)), s)
        if f == "00-本讲索引.md":
            s = re.sub(r"(?m)^(\| )(\d{2})( \| )",
                       lambda m: m.group(1) + numbers.get(m.group(2), m.group(2)) + m.group(3), s)
        if s != orig:
            write(p, s)
    for old, new in sorted(plan, key=lambda x: x[0], reverse=True):
        os.rename(os.path.join(lp, old), os.path.join(lp, new))


def fix_cross_links(vault, plans):
    """plans: {lesson_path: [(old, new), ...]} - rewrite links from ANY note in the vault.

    Renaming inside one lesson folder is not enough: sibling lessons link to
    `<lesson_path>/00-xxx` and alias them as `第 00 篇`, and those would silently
    become dead links.
    """
    def make_repl(new_prefix, num_old, num_new):
        def repl(m):
            alias = m.group(2) or ""
            if alias:
                alias = re.sub(rf"第 {num_old} 篇", f"第 {num_new} 篇", alias)
                return f"[[{new_prefix}{alias}]]"
            return f"[[{new_prefix}]]"
        return repl

    rules = []
    for lpath, plan in plans.items():
        for old, new in plan:
            stem_old, stem_new = old[:-3], new[:-3]
            # the alias separator is often escaped ([[path\|alias]]) - allow both
            pat = re.compile(r"\[\[(" + re.escape(f"{lpath}/{stem_old}") + r")((?:\\?)\|[^\]]*)?\]\]")
            rules.append((pat, make_repl(f"{lpath}/{stem_new}", old[:2], new[:2])))
    n = 0
    for dp, dn, fn in os.walk(vault):
        for f in fn:
            if not f.endswith(".md"):
                continue
            p = os.path.join(dp, f)
            s = read(p)
            orig = s
            for pat, repl in rules:
                s = pat.sub(repl, s)
            if s != orig:
                write(p, s)
                n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    rows = json.loads(read(a.manifest))
    touched = 0
    plans = {}
    for r in rows:
        lp = os.path.join(a.vault, *r["lesson_path"].split("/"))
        if not os.path.isdir(lp):
            continue
        arts = article_files(lp)
        if not any(f.startswith("00-") for f in arts):
            continue
        plan = [(f, f"{i + 1:02d}-{f[3:]}") for i, f in enumerate(arts)
                if f != f"{i + 1:02d}-{f[3:]}"]
        if not plan:
            continue
        print(f"{r['slug']}: " + ", ".join(f"{o} -> {n}" for o, n in plan))
        if not a.dry_run:
            renumber_lesson(lp, plan)
        plans[r["lesson_path"]] = plan
        touched += 1
    if plans and not a.dry_run:
        n = fix_cross_links(a.vault, plans)
        print("notes rewritten for cross-links:", n)
    print(("would fix" if a.dry_run else "fixed") + " lessons:", touched)


if __name__ == "__main__":
    main()
