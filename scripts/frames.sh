#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  frames.sh contact-sheet VIDEO OUTDIR
  frames.sh snapshot VIDEO TIME OUT
  frames.sh snapshots VIDEO OUTDIR TIME...

Notes:
  - contact-sheet: 12 frames per sheet, 5 seconds apart.
    Frame N time ≈ (N-1) * 5 seconds.
  - Do NOT use ffmpeg drawtext on this machine: fontconfig is incomplete and
    drawtext can segfault. Compute times from the contact-sheet grid instead.
EOF
}

cmd="${1:-}"
if [[ -z "$cmd" ]]; then
  usage
  exit 1
fi
shift || true

case "$cmd" in
  contact-sheet)
    video="${1:-}"; outdir="${2:-}"
    [[ -n "$video" && -n "$outdir" ]] || { usage; exit 1; }
    mkdir -p "$outdir"
    ffmpeg -y -i "$video" \
      -vf "fps=1/5,scale=320:-1,tile=4x3" \
      -vsync vfr -q:v 3 "$outdir/overview_%02d.jpg" -loglevel error
    echo "Saved contact sheets to $outdir"
    echo "12 frames/sheet, 5s apart: frame N time ≈ (N-1)*5s"
    ;;
  snapshot)
    video="${1:-}"; t="${2:-}"; out="${3:-}"
    [[ -n "$video" && -n "$t" && -n "$out" ]] || { usage; exit 1; }
    mkdir -p "$(dirname "$out")"
    ffmpeg -y -ss "$t" -i "$video" -frames:v 1 -q:v 2 "$out" -loglevel error
    echo "Saved $out"
    ;;
  snapshots)
    video="${1:-}"; outdir="${2:-}"
    [[ -n "$video" && -n "$outdir" ]] || { usage; exit 1; }
    shift 2
    [[ $# -gt 0 ]] || { usage; exit 1; }
    mkdir -p "$outdir"
    for t in "$@"; do
      safe="${t//:/-}"
      safe="${safe// /_}"
      ffmpeg -y -ss "$t" -i "$video" -frames:v 1 -q:v 2 "$outdir/t${safe}.png" -loglevel error
      echo "Saved $outdir/t${safe}.png"
    done
    ;;
  *)
    usage
    exit 1
    ;;
esac
