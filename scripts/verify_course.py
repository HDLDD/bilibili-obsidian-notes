#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify a course vault in one pass: links, images, structure, tables, coverage.

  python verify_course.py --vault "<vault>/<course>" [--manifest work/manifest.json]
                          [--asr "解条(?!件),悬度"] [--strict]

--asr entries are regexes, comma-separated. Chinese has no word boundaries, so a
two-character ASR term can match inside a legitimate word (解条 hits 定解条件).
Write a negative lookahead when that happens: 解条(?!件).

Exit code 1 when anything is wrong (use --strict to also fail on soft findings).

Checks
  links     [[...]] resolve (path-qualified, relative-to-note, or unique basename)
  images    ![..](..) exist; every asset is referenced somewhere
  structure every lesson has 00-本讲索引.md, 99-扩展笔记.md and >=1 article
  frontmatter  title == H1, part/source/duration agree with the manifest
  nav       本讲索引 links prev/next lessons
  tables    column count constant per table; no raw | inside a table row's math
  coverage  every article is listed in its 本讲索引; every lesson is linked from
            its chapter index and from the course index
  hygiene   placeholder text, ASR residue, 待核对 count
"""
import argparse
import io
import json
import os
import re
import sys

PLACEHOLDERS = ("待补充", "TODO", "FIXME", "（各讲", "占位待", "此处略")
# alt text may itself contain a balanced pair of brackets (code like a[n] in a caption)
MD_IMG = re.compile(r"!\[((?:[^\[\]]|\[[^\]]*\])*)\]\(([^)]+?\.(?:png|jpe?g|gif))\)", re.I)
CODE_LANGS = ("c", "cpp", "python", "py", "java", "js", "bash", "sh")
PAIRS = {")": "(", "]": "[", "}": "{"}
GENERIC_ASR = ("麦克斯韦",)  # replaced by --asr per course


def check_code_blocks(rel, s, hard, soft):
    """Programming courses often have no local compiler, so 'it compiles' cannot be
    verified. Bracket/quote balance is the cheap proxy that catches transcription
    damage (a dropped } or an unterminated " from reading the slide)."""
    for m in re.finditer(r"```(\w+)\n(.*?)```", s, re.S):
        lang, body = m.group(1).lower(), m.group(2)
        if lang not in CODE_LANGS or "…" in body or "..." in body:
            continue
        stripped = re.sub(r'"(?:\\.|[^"\\])*"', '""', body)
        stripped = re.sub(r"'(?:\\.|[^'\\])*'", "''", stripped)
        stripped = re.sub(r"//[^\n]*", "", stripped)
        stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.S)
        stripped = re.sub(r"(?m)#.*$", "", stripped)
        stack = []
        bad = None
        for ch in stripped:
            if ch in "([{":
                stack.append(ch)
            elif ch in ")]}":
                if not stack or stack.pop() != PAIRS[ch]:
                    bad = "unbalanced bracket"
                    break
        if bad is None and stack:
            bad = "unclosed " + stack[-1]
        if bad:
            hard.append((rel, "code block " + bad, f"```{lang}"))
        # quote parity stays a hint, so keep it cheap to read: splice the
        # backslash-continued lines C joins before phase 2, otherwise a string
        # literal deliberately broken across two lines reads as an odd count
        q = re.sub(r"\\\s*\n\s*", "", body)
        q = re.sub(r"//[^\n]*", "", q)
        q = re.sub(r"/\*.*?\*/", "", q, flags=re.S)
        q = re.sub(r'"(?:\\.|[^"\\])*"', '""', q)
        if q.count('"') % 2:
            soft.append((rel, "check quotes in code block", f"```{lang}"))


def read(p):
    return io.open(p, encoding="utf-8", errors="replace").read()


def norm_dur(x):
    if not x:
        return None
    parts = str(x).strip().split(":")
    try:
        if len(parts) == 2:
            return f"{int(parts[0])}:{int(parts[1]):02d}"
        if len(parts) == 3:
            return f"{int(parts[0]) * 60 + int(parts[1])}:{int(parts[2]):02d}"
    except ValueError:
        return None
    return str(x).strip()


def split_row(line):
    return re.split(r"(?<!\\)\|", line.strip())


def collect(md):
    out = []
    for dp, dn, fn in os.walk(md):
        for f in fn:
            if f.endswith(".md"):
                out.append(os.path.join(dp, f))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True)
    ap.add_argument("--manifest")
    ap.add_argument("--asr", default="")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    root = a.vault
    manifest = json.loads(read(a.manifest)) if a.manifest and os.path.isfile(a.manifest) else []
    asr_terms = [t for t in a.asr.split(",") if t.strip()]

    md = collect(root)
    by_base = {}
    for p in md:
        by_base.setdefault(os.path.basename(p)[:-3], []).append(p)

    hard, soft = [], []
    links = imgs = 0
    for p in md:
        rel = os.path.relpath(p, root)
        s = read(p)
        for m in re.finditer(r"!?\[\[([^\]]+)\]\]", s):
            raw = m.group(1)
            links += 1
            target = raw.split("\\|")[0].split("|")[0].split("#")[0].strip()
            if not target:
                continue
            if target.startswith("../") or target.startswith("./"):
                hard.append((rel, "relative wikilink (Obsidian cannot resolve)", target))
                continue
            ok = False
            for base in (root, os.path.dirname(p)):
                q = os.path.normpath(os.path.join(base, target))
                if os.path.isfile(q) or os.path.isfile(q + ".md"):
                    ok = True
                    break
            if ok:
                continue
            bn = target.replace("\\", "/").split("/")[-1]
            cand = by_base.get(bn, [])
            parent = os.path.normpath(os.path.join(root, *target.split("/")[:-1]))
            # check "not written yet" before the basename fallback: every lesson has a
            # 00-本讲索引.md, so a path-qualified link to a lesson that is still pending
            # would otherwise be mislabelled as an ambiguous link
            if "/" in target and not os.path.isfile(os.path.normpath(os.path.join(root, target) + ".md")) \
                    and os.path.isdir(parent):
                soft.append((rel, "link target not written yet", raw))
            elif not cand:
                hard.append((rel, "dead link", raw))
            elif len(cand) > 1:
                hard.append((rel, "ambiguous link (add the vault path)", raw))
        for m in MD_IMG.finditer(s):
            tgt = m.group(2).strip()
            imgs += 1
            if tgt.startswith("http"):
                continue
            if not os.path.isfile(os.path.normpath(os.path.join(os.path.dirname(p), tgt))):
                hard.append((rel, "missing image", tgt))
        lines = s.split("\n")
        i = 0
        while i < len(lines):
            if lines[i].strip().startswith("|") and i + 1 < len(lines) and \
                    re.match(r"^\s*\|[\s:\-|]+\|\s*$", lines[i + 1]):
                ncol = len(split_row(lines[i])) - 2
                j = i + 2
                while j < len(lines) and lines[j].strip().startswith("|"):
                    if len(split_row(lines[j])) - 2 != ncol:
                        hard.append((rel, "table column mismatch",
                                     f"line {j + 1}: expected {ncol}"))
                        break
                    if re.search(r"\\(?:left|right|big|Big|bigg|Bigg)\s*\|", lines[j]):
                        hard.append((rel, "raw | in table math (use \\lvert/\\rvert)",
                                     f"line {j + 1}"))
                    j += 1
                i = j
            else:
                i += 1
        for kw in PLACEHOLDERS:
            if kw in s:
                soft.append((rel, "placeholder text", kw))
        check_code_blocks(rel, s, hard, soft)
        for t in asr_terms:
            try:
                rx = re.compile(t)
            except re.error:
                rx = re.compile(re.escape(t))
            for m in rx.finditer(s):
                soft.append((rel, "ASR residue", t,
                             s[max(0, m.start() - 8):m.end() + 8].replace("\n", " ")))

    # structure / frontmatter against the manifest
    stats = []
    for r in manifest:
        lp = os.path.join(root, *(r.get("lesson_path") or "").split("/"))
        if not os.path.isdir(lp):
            hard.append((r.get("slug"), "lesson folder missing"))
            continue
        arts = [f for f in sorted(os.listdir(lp)) if re.match(r"^\d{2}-.*\.md$", f)
                and not f.startswith(("00-", "99-"))]
        for f in os.listdir(lp):
            if f.startswith("00-") and f != "00-本讲索引.md":
                hard.append((r["slug"], "article uses the reserved 00- prefix", f))
            if f.startswith("99-") and f != "99-扩展笔记.md":
                hard.append((r["slug"], "file uses the reserved 99- prefix", f))
        for need in ("00-本讲索引.md", "99-扩展笔记.md"):
            if not os.path.isfile(os.path.join(lp, need)):
                hard.append((r["slug"], "missing", need))
        if not arts:
            hard.append((r["slug"], "no knowledge articles"))
        idx = os.path.join(lp, "00-本讲索引.md")
        itext = read(idx) if os.path.isfile(idx) else ""
        for art in arts:
            if art[:-3] not in itext:
                hard.append((r["slug"], "article not listed in 本讲索引", art[:-3]))
        if r.get("part") and f"上一讲" not in itext and str(r["slug"]).count("-") and \
                r["slug"] not in ("1-1", "0-1"):
            soft.append((os.path.relpath(idx, root), "no prev/next nav in 本讲索引"))
        for f in arts + ["99-扩展笔记.md"]:
            p = os.path.join(lp, f)
            if not os.path.isfile(p):
                continue
            s = read(p)
            fm = s.split("---", 2)[1] if s.startswith("---") else ""
            mt = re.search(r'^title:\s*"(.*?)"', fm, re.M)
            mh = re.search(r"^#\s+(.+)$", s, re.M)
            if mt and mh and mt.group(1).strip() != mh.group(1).strip():
                hard.append((os.path.relpath(p, root), "H1 != frontmatter title"))
            if f != "99-扩展笔记.md":
                if r.get("part") is not None:
                    mp = re.search(r"^part:\s*(\d+)", fm, re.M)
                    if not mp or int(mp.group(1)) != int(r["part"]):
                        hard.append((os.path.relpath(p, root), "part mismatch"))
                if r.get("duration"):
                    md_ = re.search(r'^duration:\s*"?([^"\n]+)"?', fm, re.M)
                    if not md_ or norm_dur(md_.group(1)) != norm_dur(r["duration"]):
                        hard.append((os.path.relpath(p, root), "duration mismatch",
                                     md_.group(1) if md_ else None, r["duration"]))
                if r.get("url") and f"p={r['part']}" not in s:
                    soft.append((os.path.relpath(p, root), "source url missing/wrong part"))
        adir = os.path.join(lp, "assets")
        stats.append((r["slug"], len(arts), len(os.listdir(adir)) if os.path.isdir(adir) else 0))

    # index coverage
    for r in manifest:
        cip = os.path.join(root, *(r.get("folder", "").split("/")), "00-本章索引.md")
        if not os.path.isfile(cip):
            hard.append((r["folder"], "chapter index missing"))
        elif f"[[{r['lesson_path']}/00-本讲索引" not in read(cip):
            soft.append((r["slug"], "not linked from chapter index (run fill_indexes.py)"))
    cpath = os.path.join(root, "00-课程索引.md")
    if os.path.isfile(cpath) and manifest:
        t = read(cpath)
        for r in manifest:
            if f"[[{r['lesson_path']}/00-本讲索引" not in t:
                soft.append((r["slug"], "not linked from course index (run fill_indexes.py)"))

    # unused assets
    used = set()
    for p in md:
        for m in MD_IMG.finditer(read(p)):
            used.add(os.path.normpath(os.path.join(os.path.dirname(p),
                                                   m.group(2).strip())).lower())
    unused = [os.path.relpath(os.path.join(dp, f), root)
              for dp, dn, fn in os.walk(root) for f in fn
              if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))
              and os.path.normpath(os.path.join(dp, f)).lower() not in used]
    verify = sum(read(p).count("待核对") for p in md)

    print(f"notes={len(md)} wikilinks={links} images_refs={imgs} "
          f"articles={sum(s[1] for s in stats)} assets={sum(s[2] for s in stats)} "
          f"unused_assets={len(unused)} 待核对={verify}")
    for s in stats:
        print("  lesson", *s)
    for x in unused[:20]:
        print("  UNUSED", x)
    print(f"HARD={len(hard)} SOFT={len(soft)}")
    for x in hard[:60]:
        print("  HARD", *x)
    for x in soft[:40]:
        print("  SOFT", *x)
    bad = bool(hard) or (a.strict and bool(soft)) or bool(unused)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
