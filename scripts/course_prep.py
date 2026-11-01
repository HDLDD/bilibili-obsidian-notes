#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Whole-course driver: metadata -> manifest/skeleton -> acquire -> keyframes.

Subcommands
  meta      <url> --work DIR                 fetch series metadata -> work/meta.json
  manifest  --work DIR --map map.json --vault DIR   build manifest.json + vault skeleton + index stubs
  acquire   --work DIR EP PAGE                download + transcribe + contact sheets (idempotent)
  keys      --work DIR EP 90,210,...          extract 1080p frames -> work/EP/keyframes
  status    --work DIR                        which episodes already have video/transcript/sheets

Why idempotent: a long course is acquired once by the orchestrating agent and then read by
many note-writing subagents. Re-running must never redo finished work, and it must never
depend on an in-progress file (transcript.txt appears only when a whole pass finishes).

Environment: SENSE_THREADS (default 2) and OPENBLAS_NUM_THREADS (default 1) keep several
SenseVoice processes from thrashing an 8-core box.
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bili_meta  # noqa: E402

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")
SHEET_INTERVAL = int(os.environ.get("SHEET_INTERVAL", "15"))

# a tail chunk shorter than one utterance decodes to bare punctuation; keeping it
# would hand the note writers something that looks like speech
PUNCT_ONLY = re.compile(r"^[\s。，、.！!？?…：:；;·\-—~~]+$")

MODEL_HELP = """SenseVoice model directory not found.
Set SENSEVOICE_MODEL_DIR to a folder containing model.int8.onnx and tokens.txt, e.g.
  export SENSEVOICE_MODEL_DIR="/path/to/models"
Download the model once (either source works):
  python -c "from modelscope import snapshot_download; \\
    snapshot_download('sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17', local_dir='./models')"
  # or from Hugging Face: csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17
See README.md » Transcription model."""


def model_dir() -> Path:
    # Windows users set env values with setx, which keeps the surrounding quotes
    raw = os.environ.get("SENSEVOICE_MODEL_DIR", "").strip().strip('"').strip("'")
    d = Path(raw).expanduser() if raw else None
    if not d or not (d / "model.int8.onnx").exists():
        raise SystemExit(MODEL_HELP)
    return d


def ytdlp() -> str:
    for cand in (os.environ.get("YTDLP"), shutil.which("yt-dlp")):
        if cand and Path(cand).exists():
            return cand
    raise SystemExit("yt-dlp not found; set YTDLP=/path/to/yt-dlp or install it (pipx install yt-dlp)")


def run(cmd, log=None):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    if log:
        with open(log, "a", encoding="utf-8") as fh:
            fh.write("+ " + " ".join(str(c) for c in cmd) + "\n")
            p = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT)
    else:
        p = subprocess.run(cmd)
    if p.returncode != 0:
        raise SystemExit(f"command failed ({p.returncode}): {cmd[0]}")
    return p


def fmt(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def cmd_meta(a):
    out = Path(a.work) / "meta.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    final_url = bili_meta.resolve_url(a.url)
    match = re.search(r"(BV[0-9A-Za-z]+)", final_url)
    if not match:
        raise SystemExit(f"could not find a BV id in {final_url}")
    bvid = match.group(1)
    info = bili_meta.request_json(
        f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}")
    if info.get("code") != 0:
        raise SystemExit(f"Bilibili API error {info.get('code')}: {info.get('message')}")
    d = info["data"]
    data = {
        "bvid": bvid,
        "title": d.get("title"),
        "owner": (d.get("owner") or {}).get("name"),
        "series_url": f"https://www.bilibili.com/video/{bvid}/",
        "pages": [{"index": p.get("page"), "part": p.get("part"),
                   "duration": p.get("duration"), "cid": p.get("cid")}
                  for p in d.get("pages", [])],
    }
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(p["duration"] for p in data["pages"])
    print(f"{data['title']}\nUP: {data['owner']}  parts={len(data['pages'])}  total={fmt(total)}")
    for p in data["pages"]:
        print(f"  P{p['index']:>3}  {fmt(p['duration']):>7}  {p['part']}")
    print("\nNext: write a chapter map json, then run: manifest --map that.json")


CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def guess_chapter(title: str):
    m = re.search(r"第([一二三四五六七八九十]+)章", title or "")
    if m and m.group(1) in CN:
        return CN[m.group(1)]
    return None


QUALITY_TAIL = re.compile(r"(?:[_\s](?:高清|超清|标清|全高清|蓝光|\d{3,4}P))+\s*$")


def clean_part_title(part: str) -> str:
    """Keep the instructor's own numbering and lead-in sentence, drop the quality tail."""
    return QUALITY_TAIL.sub("", (part or "").strip())


def default_lesson_title(part: str) -> str:
    """`1.1.1 变量定义：变量是做什么的_高清` -> `变量定义`.

    Course parts are usually numbered 周.节.讲 and carry a descriptive tail; neither
    belongs in a folder name that every wikilink has to repeat.
    """
    t = re.sub(r"(?:[_\s](?:高清|超清|标清|全高清|蓝光|\d{3,4}P))+\s*$", "", (part or "").strip())
    t = re.sub(r"^\s*\d+(?:[.\-]\d+)*\s*", "", t)
    t = re.split(r"[：:——]", t, maxsplit=1)[0]
    return t.strip() or "未命名讲"


def cmd_manifest(a):
    work = Path(a.work)
    meta = json.loads((work / "meta.json").read_text(encoding="utf-8"))
    cmap = json.loads(Path(a.map).read_text(encoding="utf-8"))
    vault = Path(a.vault)
    rows, seen = [], {}
    for page in meta["pages"]:
        ch = next((c for c in cmap if page["index"] in c.get("pages", [])), None)
        if ch is None:
            print(f"  ! P{page['index']} not in chapter map -> 未归类")
            ch = {"chapter": "0", "topic": "未归类", "lesson_titles": {}}
        num = str(ch["chapter"])
        topic = ch["topic"]
        seen[num] = seen.get(num, 0) + 1
        seq = seen[num]
        slug = f"{num}-{seq}"
        lesson_title = (ch.get("lesson_titles") or {}).get(str(page["index"])) or \
            default_lesson_title(page["part"])
        folder = f"第{num}章-{topic}" if num != "0" else f"附录-{topic}"
        folder = f"第{num}章-{topic}" if num != "0" else f"附录-{topic}"
        lesson_folder = f"{slug}-{lesson_title}"
        rows.append({
            "chapter": num, "chapter_topic": topic, "folder": folder,
            "seq": seq, "slug": slug, "part": page["index"],
            "part_title": clean_part_title(page["part"]), "lesson_title": lesson_title,
            "lesson_folder": lesson_folder,
            "lesson_path": f"{folder}/{lesson_folder}",
            "duration": fmt(page["duration"]), "duration_s": page["duration"],
            "work": f"e{page['index']:02d}",
            "url": f"https://www.bilibili.com/video/{meta['bvid']}/?p={page['index']}",
        })
        (vault / folder / lesson_folder / "assets").mkdir(parents=True, exist_ok=True)
    (work / "manifest.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    write_indexes(vault, rows, meta, force=a.force_indexes)
    print(f"manifest: {len(rows)} lessons, {len({r['folder'] for r in rows})} chapters -> {vault}")


def write_indexes(vault: Path, rows, meta, force=False):
    """Chapter index stubs + course index. Existing files are kept unless force."""
    by_ch = {}
    for r in rows:
        by_ch.setdefault(r["chapter"], []).append(r)
    order = [c for c in by_ch if c != "0"] + ([c for c in by_ch if c == "0"])
    label = lambda c: "附录" if c == "0" else f"第{c}章"
    for ch in order:
        items = by_ch[ch]
        topic = items[0]["chapter_topic"]
        path = vault / items[0]["folder"] / "00-本章索引.md"
        if path.exists() and not force:
            continue
        head = ["---", f'title: "{label(ch)} · {topic} · 本章索引"',
                f'course: "{meta["title"]}"', f'chapter: "{ch}"', "type: 章索引",
                "tags:", "  - 课程笔记", "  - 章索引", "---", "", f"# {label(ch)} · {topic}", "",
                "> [!info] 本章信息",
                f"> - 视频：[{meta['bvid']}]({meta['series_url']}) · UP：{meta['owner']}",
                "> - 「笔记」列由 fill_indexes.py 回填，子代理不要编辑本文件。", "",
                "## 本讲一览", "", "| 讲 | 分 P | 视频原标题 | 时长 | 笔记 |",
                "| --- | --- | --- | --- | --- |"]
        body = [f"| {r['slug']} | P{r['part']} | {r['part_title']} | {r['duration']} | "
                f"待整理 · [B站]({r['url']}) |" for r in items]
        tail = ["", f"> [!warning] 整理状态", f"> 本章 {len(items)} 讲待整理。", "",
                "## 本章主线", "", "（各讲完成后补充：本章讲什么、与上下游章节的关系。）", "",
                "## 公式速查", "", "（各讲完成后补充。）", "", "## 易错点", "",
                "（各讲完成后补充。）", ""]
        path.write_text("\n".join(head + body + tail), encoding="utf-8")
    cpath = vault / "00-课程索引.md"
    if cpath.exists() and not force:
        return
    nav = [f"| {label(c)} | {'P%d-P%d' % (by_ch[c][0]['part'], by_ch[c][-1]['part']) if len(by_ch[c]) > 1 else 'P%d' % by_ch[c][0]['part']} | {by_ch[c][0]['chapter_topic']} | "
           f"{len(by_ch[c])} | [[{by_ch[c][0]['folder']}/00-本章索引\\|本章索引]] |" for c in order]
    lessons = [f"| P{r['part']} | {r['slug']} | {r['part_title']} | {r['duration']} | 待整理 |"
               for c in order for r in by_ch[c]]
    total = sum(r["duration_s"] for r in rows)
    hours = f"{total // 3600}:{(total % 3600) // 60:02d}:{total % 60:02d}"
    course = f'''---
title: "{meta['title']} · 课程索引"
course: "{meta['title']}"
bvid: "{meta['bvid']}"
type: 课程索引
status: 进行中
tags:
  - 课程索引
---

# {meta['title']} · 课程索引

> [!info] 课程信息
> - UP 主：{meta['owner']}
> - 视频：[{meta['bvid']}]({meta['series_url']})
> - 共 **{len(rows)} 个分 P**，总时长 **{hours}**。
> - 按章归档；每讲一个文件夹，长讲按讲师自己划的小节拆成多篇知识点正文。

> [!abstract] 进度
> - 总进度：**0/{len(rows)} 讲**。

## 章节导航

| 章 | 分 P | 主题 | 讲数 | 本章索引 |
| --- | --- | --- | --- | --- |
{chr(10).join(nav)}

## 全部讲次

| P | 讲 | 视频原标题 | 时长 | 状态 |
| --- | --- | --- | --- | --- |
{chr(10).join(lessons)}
'''
    cpath.write_text(course, encoding="utf-8")


def duration(video: Path) -> float:
    out = subprocess.check_output([FFPROBE, "-v", "error", "-show_entries",
                                   "format=duration", "-of", "default=nw=1:nk=1",
                                   str(video)], text=True)
    return float(out.strip())


def transcribe(wav: Path, txt: Path, js: Path, threads: int):
    import numpy as np
    import sherpa_onnx
    models = model_dir()
    print("loading sensvoice...", flush=True)
    rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(models / "model.int8.onnx"), tokens=str(models / "tokens.txt"),
        num_threads=threads, use_itn=True, language="zh", debug=False)
    with wave.open(str(wav), "rb") as w:
        data = w.readframes(w.getnframes())
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    dur = len(samples) / 16000.0
    step = 60 * 16000
    rows, n = [], math.ceil(len(samples) / step)
    print(f"duration {dur:.1f}s, {n} chunks", flush=True)
    for i in range(n):
        chunk = samples[i * step:(i + 1) * step]
        if not len(chunk):
            break
        stream = rec.create_stream()
        stream.accept_waveform(16000, chunk)
        rec.decode_stream(stream)
        text = stream.result.text.strip()
        if PUNCT_ONLY.match(text):
            continue
        rows.append({"start": i * 60.0, "end": min((i + 1) * 60.0, dur), "text": text})
        s = int(rows[-1]["start"])
        print(f"[{s // 60:02d}:{s % 60:02d}] {rows[-1]['text']}", flush=True)
    js.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    txt.write_text("\n".join(
        f"[{int(r['start']) // 60:02d}:{int(r['start']) % 60:02d}] {r['text']}" for r in rows
    ) + "\n", encoding="utf-8")


def contact_sheets(d: Path, video: Path):
    out = sorted((d / "frames").glob("overview_*.jpg"))
    if out:
        print(f"overview sheets exist ({len(out)}), skip")
        return
    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-vf",
         f"fps=1/{SHEET_INTERVAL},scale=320:180,tile=4x3", "-q:v", "4",
         str(d / "frames" / "overview_%02d.jpg")])
    print(f"overview sheets: {len(list((d / 'frames').glob('overview_*.jpg')))}"
          f" (12 per sheet, {SHEET_INTERVAL}s apart)")


def cmd_acquire(a):
    work = Path(a.work)
    meta = json.loads((work / "meta.json").read_text(encoding="utf-8"))
    bvid = meta["bvid"]
    d = work / a.ep
    for sub in ("transcribe", "frames", "keyframes"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    video, wav = d / "video.mp4", d / "transcribe" / "audio_16k.wav"
    txt, js = d / "transcribe" / "transcript.txt", d / "transcribe" / "transcript.json"
    if not video.exists() or video.stat().st_size < 1_000_000:
        url = f"https://www.bilibili.com/video/{bvid}/?p={a.page}"
        run([ytdlp(), "--no-playlist", "-f", "30080+30280/bv*+ba", "--merge-output-format",
             "mp4", "--referer", "https://www.bilibili.com/", "-o", str(video), url],
            log=d / "download.log")
    else:
        print("video exists, skip download")
    if not wav.exists():
        run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-vn",
             "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)])
    if not txt.exists() or not js.exists():
        transcribe(wav, txt, js, threads=int(os.environ.get("SENSE_THREADS", "2")))
    else:
        print("transcript exists, skip transcribe")
    contact_sheets(d, video)


def cmd_keys(a):
    d = Path(a.work) / a.ep
    for t in [x for x in re.split(r"[,\s]+", a.times) if x]:
        out = d / "keyframes" / f"t{int(float(t))}.png"
        run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-ss", t,
             "-i", str(d / "video.mp4"), "-frames:v", "1", "-q:v", "2", str(out)])
        print("saved", out)


def cmd_status(a):
    work = Path(a.work)
    rows = json.loads((work / "manifest.json").read_text(encoding="utf-8")) \
        if (work / "manifest.json").exists() else []
    eps = sorted([p for p in work.glob("e*") if p.is_dir()]) or \
        [work / r["work"] for r in rows]
    for d in eps:
        v = (d / "video.mp4").exists()
        t = (d / "transcribe" / "transcript.txt").exists()
        n = len(list((d / "frames").glob("overview_*.jpg")))
        print(f"{d.name:>5}  video={'y' if v else 'n'}  transcript={'y' if t else 'n'}  sheets={n}")


def main():
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    m = sp.add_parser("meta")
    m.add_argument("--url", required=True)
    m.add_argument("--work", required=True)
    m.set_defaults(func=cmd_meta)
    mf = sp.add_parser("manifest")
    mf.add_argument("--work", required=True)
    mf.add_argument("--map", required=True, help="chapter map json: [{chapter,topic,pages,lesson_titles}]")
    mf.add_argument("--vault", required=True)
    mf.add_argument("--force-indexes", action="store_true")
    mf.set_defaults(func=cmd_manifest)
    ac = sp.add_parser("acquire")
    ac.add_argument("--work", required=True)
    ac.add_argument("ep")
    ac.add_argument("page", type=int)
    ac.set_defaults(func=cmd_acquire)
    k = sp.add_parser("keys")
    k.add_argument("--work", required=True)
    k.add_argument("ep")
    k.add_argument("times")
    k.set_defaults(func=cmd_keys)
    st = sp.add_parser("status")
    st.add_argument("--work", required=True)
    st.set_defaults(func=cmd_status)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
