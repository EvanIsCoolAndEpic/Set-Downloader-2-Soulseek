#!/bin/zsh
# Starts Set Downloader from this folder (builds the UI first if it isn't built).
cd "$(dirname "$0")"
[ -f web/dist/index.html ] || (cd web && npm run build)
exec .venv/bin/python -m setdl "$@"
