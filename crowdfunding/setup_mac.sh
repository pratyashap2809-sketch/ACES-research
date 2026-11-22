#!/bin/bash
# One-time setup on a Mac (Apple Silicon). Run from this folder:  bash setup_mac.sh
set -e
cd "$(dirname "$0")"
echo "== 1. Python =="
python3 --version || { echo "Python 3 missing: install the Command Line Tools (xcode-select --install)"; exit 1; }

echo "== 2. Ollama =="
if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is not installed."
  echo "Download it from https://ollama.com/download (Mac), open the app once, then run this script again."
  open "https://ollama.com/download" 2>/dev/null || true
  exit 1
fi
if ! curl -s http://127.0.0.1:11434/api/version >/dev/null; then
  echo "Starting Ollama..."; open -a Ollama 2>/dev/null || (ollama serve >/dev/null 2>&1 &); sleep 5
fi

echo "== 3. Models (about 2.0 GB + 3.3 GB, one-time download) =="
ollama pull llama3.2:3b
ollama pull gemma3:4b

echo "== 4. Check everything and measure speed =="
python3 sahyog.py check
echo
echo "Ready. Next:"
echo "  python3 sahyog.py serve                       # open the website + lab"
echo "  python3 sahyog.py run --preset quick          # ~10-20 min trial run"
echo "  python3 sahyog.py run --preset standard       # the real experiment"
