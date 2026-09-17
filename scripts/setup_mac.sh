#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
INSTALL_DEV=0
SKIP_INSTALL=0

usage() {
  cat <<'EOF'
Usage: ./scripts/setup_mac.sh [options]

Options:
  --dev           Install development dependencies, including pytest.
  --skip-install  Create/check configuration without installing Python packages.
  --python PATH   Python executable to use (default: python3 or $PYTHON_BIN).
  -h, --help      Show this help.

This script never overwrites .env or config/paths.local.env.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dev) INSTALL_DEV=1; shift ;;
    --skip-install) SKIP_INSTALL=1; shift ;;
    --python)
      [[ $# -ge 2 ]] || { echo "--python requires a path" >&2; exit 2; }
      PYTHON_BIN="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This setup kit targets macOS." >&2
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git is missing. Run: xcode-select --install" >&2
  exit 1
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python was not found: $PYTHON_BIN" >&2
  echo "Install Python 3.11 (Homebrew or python.org), then rerun with --python." >&2
  exit 1
fi

"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' || {
  echo "Python 3.10 or newer is required. Python 3.11 is recommended." >&2
  exit 1
}

echo "Project: ${PROJECT_ROOT}"
echo "macOS:   $(sw_vers -productVersion) ($(uname -m))"
echo "Python:  $("$PYTHON_BIN" --version 2>&1)"

if [[ $SKIP_INSTALL -eq 0 ]]; then
  if [[ ! -d "$VENV_DIR" ]]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
  fi
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel
  if [[ $INSTALL_DEV -eq 1 ]]; then
    "${VENV_DIR}/bin/python" -m pip install -r "${PROJECT_ROOT}/requirements-dev.txt"
  else
    "${VENV_DIR}/bin/python" -m pip install -r "${PROJECT_ROOT}/requirements.txt"
  fi
fi

if [[ ! -f "${PROJECT_ROOT}/.env" ]]; then
  cp "${PROJECT_ROOT}/.env.example" "${PROJECT_ROOT}/.env"
  chmod 600 "${PROJECT_ROOT}/.env"
  echo "Created .env (values are blank)."
else
  echo "Kept existing .env unchanged."
fi

if [[ ! -f "${PROJECT_ROOT}/config/paths.local.env" ]]; then
  cp "${PROJECT_ROOT}/config/paths.example.env" "${PROJECT_ROOT}/config/paths.local.env"
  chmod 600 "${PROJECT_ROOT}/config/paths.local.env"
  echo "Created config/paths.local.env (paths are blank)."
else
  echo "Kept existing config/paths.local.env unchanged."
fi

echo
echo "Setup finished. Next:"
echo "  1. Edit .env (only the services you use)."
echo "  2. Edit config/paths.local.env."
echo "  3. Run ./scripts/doctor_mac.sh"
