#!/usr/bin/env python3
"""Resolve a Bilibili / b23.tv link and dump series metadata."""
import argparse
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def request_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def resolve_url(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.geturl()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="Bilibili or b23.tv URL")
    parser.add_argument("--part", type=int, help="Bilibili part index (1-based)")
    parser.add_argument("--out", help="Write JSON to this file")
    args = parser.parse_args()

    final_url = resolve_url(args.url)
    match = re.search(r"(BV[0-9A-Za-z]+)", final_url)
    if not match:
        raise SystemExit(f"Could not find BV id in: {final_url}")
    bvid = match.group(1)

    query = urllib.parse.parse_qs(urllib.parse.urlparse(final_url).query)
    inferred_part = query.get("p", [None])[0]
    part_index = args.part or (int(inferred_part) if inferred_part else None)

    data = request_json(
        f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    )
    if data.get("code") != 0:
        raise SystemExit(f"Bilibili API error {data.get('code')}: {data.get('message')}")

    info = data["data"]
    pages = []
    for index, page in enumerate(info.get("pages", []), 1):
        pages.append(
            {
                "index": index,
                "part": page.get("part"),
                "duration": page.get("duration"),
                "cid": page.get("cid"),
                "url": f"https://www.bilibili.com/video/{bvid}/?p={index}",
            }
        )

    result = {
        "bvid": bvid,
        "title": info.get("title"),
        "owner": (info.get("owner") or {}).get("name"),
        "series_url": f"https://www.bilibili.com/video/{bvid}/",
        "resolved_url": final_url,
        "pages": pages,
        "selected": next((p for p in pages if p["index"] == part_index), None),
    }

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        selected = result["selected"]
        label = selected["part"] if selected else "(none)"
        print(f"bvid={bvid} parts={len(pages)} selected={part_index} {label}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
