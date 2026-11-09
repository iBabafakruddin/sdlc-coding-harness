#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${1:-.}"

if command -v python3 >/dev/null 2>&1; then
  python3 "$SCRIPT_DIR/install.py" "$TARGET_DIR"
else
  python "$SCRIPT_DIR/install.py" "$TARGET_DIR"
fi
