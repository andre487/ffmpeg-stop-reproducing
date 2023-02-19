#!/usr/bin/env bash
set -eufo pipefail

target=${1:-/tmp/video.mp4}

set -x
ffmpeg -y -hide_banner -listen 1 -i 'rtmp://localhost:1935/live/app' -c copy -f mp4 "$target"
