#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Normalize any yt-dlp-supported source into the meta.json shape this pipeline eats.

Bilibili keeps its own fast path (course_prep uses the web API directly); everything
else - YouTube, and the other ~1700 yt-dlp extractors - goes through here.

meta.json contract (same for both paths):
  bvid        id of the video/playlist ("bvid" is a historical name; for other sources
              this is yt-dlp's `id`)
  title       course/video title
  owner       uploader/channel name
  series_url  what to cite in the 课程索引
  source      extractor key (absent for the Bilibili path)
  pages[]     {index, part, duration, url, chapters[]}   <- chapters only when the
              uploader marked them, which is the case on most lecture channels

Chapters matter: the whole method in SKILL.md is "split the lesson the way the
instructor split it". Marked chapters answer that directly, so Step 4/5 stops
guessing section boundaries from contact sheets.

  python source_meta.py --url URL --out work/meta.json
  python source_meta.py --url URL --out work/meta.json --playlist   # one entry per video
  python source_meta.py --from-json saved.json --out work/meta.json # offline/debug
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
BILI_HOSTS = ("bilibili.com", "b23.tv")


def is_bilibili(url: str) -> bool:
    return any(h in (url or "") for h in BILI_HOSTS)


def ytdlp() -> str:
    for cand in (os.environ.get("YTDLP"), shutil.which("yt-dlp")):
        if cand and Path(cand).exists():
            return cand
    raise SystemExit("yt-dlp not found; set YTDLP=/path/to/yt-dlp or install it (pipx install yt-dlp)")


def dump_json(url: str, playlist: bool) -> dict:
    cmd = [ytdlp(), "-J", "--no-warnings"]
    cmd.append("--flat-playlist" if playlist else "--no-playlist")
    cmd.append(url)
    print("+", " ".join(cmd), file=sys.stderr, flush=True)
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        raise SystemExit(f"yt-dlp failed ({p.returncode}): {(p.stderr or '').strip()[-500:]}")
    return json.loads(p.stdout)


def chapters_of(info: dict) -> list:
    """Uploader-defined chapters, as {title, start, end} in seconds."""
    out = []
    for c in info.get("chapters") or []:
        title = (c.get("title") or "").strip()
        start, end = c.get("start_time"), c.get("end_time")
        if not title or start is None:
            continue
        out.append({"title": title, "start": int(start),
                    "end": int(end) if end is not None else None})
    return out


def entry(index: int, info: dict) -> dict:
    url = info.get("webpage_url") or info.get("url") or ""
    if url and not url.startswith("http") and info.get("ie_key"):
        url = f"https://www.{info['ie_key'].lower()}.com/"
    return {
        "index": index,
        "part": info.get("title") or f"片段{index}",
        "duration": info.get("duration"),
        "url": url,
        "chapters": chapters_of(info),
    }


def probe_duration(url: str):
    """Seconds, for sources that don't report one (a direct-file URL has no metadata)."""
    ffprobe = os.environ.get("FFPROBE", "ffprobe")
    try:
        out = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                              "-of", "default=nw=1:nk=1", url],
                             capture_output=True, text=True, timeout=25)
        return int(float(out.stdout.strip()))
    except Exception:
        return None


def show(seconds) -> str:
    if not seconds:
        return "   ?:??"
    m, s = int(seconds) // 60, int(seconds) % 60
    return f"{m:>4}:{s:02d}"


def normalize(info: dict, url: str) -> dict:
    if info.get("_type") == "playlist":
        entries = info.get("entries") or []
        pages = [entry(i + 1, e) for i, e in enumerate(entries) if e]
        missing = sum(1 for p in pages if not p["duration"])
        if missing:
            print(f"note: {missing}/{len(pages)} 条没有时长（flat 列表常见），"
                  "manifest 的时长列会留空，采集后由 ffprobe 补齐", file=sys.stderr)
        title = info.get("title") or (pages[0]["part"] if pages else url)
        owner = info.get("uploader") or next((e.get("channel") for e in entries if e), None)
        vid = info.get("playlist_id") or (pages[0]["url"].split("/")[-1] if pages else url)
    else:
        pages, title, owner, vid = [entry(1, info)], info.get("title"), info.get("uploader"), info.get("id")
    for p in pages:
        if not p["duration"] and p["url"]:
            p["duration"] = probe_duration(p["url"])
    return {
        "bvid": vid,
        "title": title,
        "owner": owner,
        "series_url": info.get("webpage_url") or url,
        "source": info.get("extractor_key") or info.get("ie_key") or "",
        "pages": pages,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="any yt-dlp-supported video or playlist URL")
    ap.add_argument("--out", required=True, help="meta.json path")
    ap.add_argument("--playlist", action="store_true",
                    help="treat the URL as a list and emit one page per video (metadata is shallow)")
    ap.add_argument("--from-json", help="normalize a saved `yt-dlp -J` dump instead of fetching")
    a = ap.parse_args()

    if bool(a.url) == bool(a.from_json):
        raise SystemExit("give exactly one of --url / --from-json")
    if a.url and is_bilibili(a.url):
        raise SystemExit("这是 B 站链接：走 bili_meta.py / course_prep.py meta（B 站快速路径），"
                         "本脚本只处理其它站点")
    info = json.loads(Path(a.from_json).read_text(encoding="utf-8")) if a.from_json else dump_json(a.url, a.playlist)
    data = normalize(info, a.url or "")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    known = [p["duration"] for p in data["pages"] if p["duration"]]
    total = sum(known)
    total_txt = (f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"
                 if known else "未知")
    print(f"{data['title']}\n来源: {data['source'] or '?'}  UP: {data['owner']}  "
          f"parts={len(data['pages'])}  total={total_txt}")
    for p in data["pages"]:
        mark = f"  [{len(p['chapters'])} 章节]" if p["chapters"] else ""
        print(f"  #{p['index']:>3}  {show(p['duration'])}  {p['part']}{mark}")
    print(f"\nsaved -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
