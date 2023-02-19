#!/usr/bin/env bash
set -exufo pipefail

cd "$(dirname "$0")"
python3 -m venv .venv

.venv/bin/pip install -r requirements.txt
