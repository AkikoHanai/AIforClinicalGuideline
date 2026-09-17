#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ONLINE=0
RUN_TESTS=0
FAILURES=0
WARNINGS=0

usage() {
  cat <<'EOF'
Usage: ./scripts/doctor_mac.sh [--online] [--tests]

  --online  Verify AWS credentials with STS (network access required).
  --tests   Run pytest after environment checks.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --online) ONLINE=1; shift ;;
    --tests) RUN_TESTS=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

pass() { printf 'PASS  %s\n' "$1"; }
warn() { printf 'WARN  %s\n' "$1"; WARNINGS=$((WARNINGS + 1)); }
fail() { printf 'FAIL  %s\n' "$1"; FAILURES=$((FAILURES + 1)); }

load_env_file() {
  local file="$1"
  if [[ -f "$file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$file"
    set +a
  fi
}

echo "AIforClinicalGuideline Mac doctor"
echo "Project: ${PROJECT_ROOT}"
echo

[[ "$(uname -s)" == "Darwin" ]] && pass "macOS $(sw_vers -productVersion) ($(uname -m))" || fail "Not running on macOS"
command -v git >/dev/null 2>&1 && pass "git $(git --version | awk '{print $3}')" || fail "git is missing (run xcode-select --install)"

if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
  PYTHON="${PROJECT_ROOT}/.venv/bin/python"
  pass "virtual environment exists"
else
  PYTHON="$(command -v python3 || true)"
  warn ".venv is missing; run ./scripts/setup_mac.sh"
fi

if [[ -n "$PYTHON" ]]; then
  if "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
    pass "$($PYTHON --version 2>&1)"
  else
    fail "Python 3.10+ is required"
  fi
else
  fail "python3 is missing"
fi

[[ -f "${PROJECT_ROOT}/.env" ]] && pass ".env exists and is git-ignored" || warn ".env is missing; setup_mac.sh creates it"
[[ -f "${PROJECT_ROOT}/config/paths.local.env" ]] && pass "local path configuration exists" || warn "config/paths.local.env is missing"

load_env_file "${PROJECT_ROOT}/.env"
load_env_file "${PROJECT_ROOT}/config/paths.local.env"

if [[ -n "$PYTHON" ]]; then
  missing_modules="$($PYTHON -c 'import importlib.util
mods={"requests":"requests","pandas":"pandas","openpyxl":"openpyxl","tqdm":"tqdm","dotenv":"python-dotenv","anthropic":"anthropic","boto3":"boto3","chromadb":"chromadb","sentence_transformers":"sentence-transformers","pdfplumber":"pdfplumber","fuzzywuzzy":"fuzzywuzzy"}
print(", ".join(label for module,label in mods.items() if importlib.util.find_spec(module) is None))' 2>/dev/null || true)"
  [[ -z "$missing_modules" ]] && pass "required Python imports" || fail "missing Python packages: ${missing_modules}"
fi

if [[ -n "${GL_GOOGLE_DRIVE_ROOT:-}" ]]; then
  [[ -d "$GL_GOOGLE_DRIVE_ROOT" ]] && pass "Google Drive root is reachable" || fail "GL_GOOGLE_DRIVE_ROOT does not exist"
else
  warn "GL_GOOGLE_DRIVE_ROOT is not configured"
fi

if [[ -n "${GL_LOCAL_WORKSPACE:-}" ]]; then
  [[ -d "$GL_LOCAL_WORKSPACE" ]] && pass "local workspace is reachable" || warn "GL_LOCAL_WORKSPACE does not exist yet"
else
  warn "GL_LOCAL_WORKSPACE is not configured"
fi

if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  pass "ANTHROPIC_API_KEY is configured (value hidden)"
else
  warn "ANTHROPIC_API_KEY is blank; Direct API generation will be skipped"
fi

if command -v aws >/dev/null 2>&1; then
  pass "AWS CLI is installed"
  if [[ $ONLINE -eq 1 ]]; then
    if aws sts get-caller-identity >/dev/null 2>&1; then
      pass "AWS credentials are valid"
    else
      fail "AWS credential check failed"
    fi
  else
    warn "AWS credentials were not contacted; rerun with --online to verify"
  fi
else
  warn "AWS CLI is not installed; required only for AWS/Bedrock deployment"
fi

if git -C "$PROJECT_ROOT" check-ignore -q .env \
  && git -C "$PROJECT_ROOT" check-ignore -q config/paths.local.env; then
  pass "secret/local configuration files are excluded from Git"
else
  fail ".env or paths.local.env is not excluded from Git"
fi

tracked_secrets="$(git -C "$PROJECT_ROOT" ls-files '.env' 'config/paths.local.env')"
[[ -z "$tracked_secrets" ]] && pass "no local secret configuration is tracked" || fail "tracked local configuration: ${tracked_secrets}"

if [[ $RUN_TESTS -eq 1 ]]; then
  if [[ -n "$PYTHON" ]] && "$PYTHON" -m pytest --version >/dev/null 2>&1; then
    (cd "$PROJECT_ROOT" && "$PYTHON" -m pytest -q) && pass "pytest" || fail "pytest failed"
  else
    fail "pytest is unavailable; rerun setup_mac.sh --dev"
  fi
fi

echo
echo "Result: ${FAILURES} failure(s), ${WARNINGS} warning(s)"
[[ $FAILURES -eq 0 ]]
