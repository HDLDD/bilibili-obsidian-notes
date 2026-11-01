#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chunked SenseVoice transcription via sherpa-onnx (no external project needed).

transcript.txt is written only after the whole pass finishes, so "does the file
exist" is a reliable progress signal for a resumable pipeline.
"""
import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = SKILL_ROOT / "references" / "course-config.json"

MODEL_HELP = """SenseVoice model directory not found.
Pass --model-dir or set SENSEVOICE_MODEL_DIR to a folder containing
model.int8.onnx and tokens.txt, e.g.
  export SENSEVOICE_MODEL_DIR="/path/to/models"
Download the model once (either source works):
  python -c "from modelscope import snapshot_download; \\
    snapshot_download('sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17', local_dir='./models')"
  # or from Hugging Face: csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17
See README.md » Transcription model."""


def read_config(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def resolve_model_dir(cli_value, config: dict) -> Path:
    # Windows users set env values with setx, which keeps the surrounding quotes
    for raw in (cli_value, os.environ.get("SENSEVOICE_MODEL_DIR"),
                config.get("sensevoice_model_dir")):
        raw = (raw or "").strip().strip('"').strip("'")
        if raw:
            d = Path(raw).expanduser()
            if (d / "model.int8.onnx").exists():
                return d
    raise SystemExit(MODEL_HELP)


def to_wav(input_path: Path, output_path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(output_path),
            "-loglevel",
            "error",
        ],
        check=True,
    )


def get_duration(wav_path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(wav_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def fmt_time(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02d}:{secs:02d}"


# a chunk shorter than one utterance often decodes to bare punctuation, which then
# reads like real speech to whatever turns the transcript into notes
PUNCT_ONLY = re.compile(r"^[\s。，、.！!？?…：:；;·~—-]+$")


def load_recognizer(models: Path, threads: int):
    try:
        import sherpa_onnx
    except ImportError:
        raise SystemExit("sherpa_onnx is not installed: pip install sherpa-onnx numpy")
    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(models / "model.int8.onnx"),
        tokens=str(models / "tokens.txt"),
        num_threads=threads,
        use_itn=True,
        language="zh",
        debug=False,
    )


def transcribe_chunk(rec, wav_path: Path, start: float, end: float) -> str:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        chunk_path = Path(tmp.name)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(start),
                "-to",
                str(end),
                "-i",
                str(wav_path),
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(chunk_path),
                "-loglevel",
                "error",
            ],
            check=True,
        )
        with wave.open(str(chunk_path), "rb") as w:
            frames = w.readframes(w.getnframes())
        import numpy as np
        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        stream = rec.create_stream()
        stream.accept_waveform(16000, samples)
        rec.decode_stream(stream)
        return stream.result.text.strip()
    finally:
        chunk_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Video or audio file")
    parser.add_argument("--out-dir", required=True, help="Output directory")
    parser.add_argument("--chunk-seconds", type=int, default=None)
    parser.add_argument("--threads", type=int, default=int(os.environ.get("SENSE_THREADS", "2")))
    parser.add_argument("--model-dir", default=None, help="Folder with model.int8.onnx + tokens.txt")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args()

    config = read_config(Path(args.config))
    models = resolve_model_dir(args.model_dir, config)
    chunk_seconds = int(args.chunk_seconds or config.get("chunk_seconds", 60))

    input_path = Path(args.input).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    wav_path = out_dir / "audio_16k.wav"
    print(f"Converting to 16k mono wav: {wav_path}")
    to_wav(input_path, wav_path)

    duration = get_duration(wav_path)
    print(f"Duration: {duration:.1f}s; chunk: {chunk_seconds}s; threads: {args.threads}")

    rec = load_recognizer(models, args.threads)
    rows = []
    n = math.ceil(duration / chunk_seconds)
    for index in range(n):
        start = index * chunk_seconds
        end = min(start + chunk_seconds, duration)
        text = transcribe_chunk(rec, wav_path, start, end)
        if text and not PUNCT_ONLY.match(text):
            rows.append({"start": start, "end": end, "text": text})
            print(f"[{fmt_time(start)}] {text}", flush=True)

    txt_path = out_dir / "transcript.txt"
    json_path = out_dir / "transcript.json"
    txt_path.write_text(
        "\n".join(f"[{fmt_time(row['start'])}] {row['text']}" for row in rows) + "\n",
        encoding="utf-8",
    )
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(rows)} segments -> {txt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
