#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SOURCE=""
OUTPUT=""
INCLUDE_DATA=0

usage() {
  cat <<'EOF'
Usage:
  ./scripts/package_local_workspace.sh --source DIR --output FILE [--include-data]

Creates a local tar.gz for transfer by AirDrop or an encrypted external drive.
It always excludes .env, credentials, virtual environments, Git metadata,
caches and logs. By default it also excludes CQ data and review outputs.

Options:
  --source DIR     Local review-platform/workspace directory to package.
  --output FILE    Output file; must end in .migration.tar.gz.
  --include-data   Include data/ and review/ after confirming local handling.
  -h, --help       Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source) SOURCE="${2:-}"; shift 2 ;;
    --output) OUTPUT="${2:-}"; shift 2 ;;
    --include-data) INCLUDE_DATA=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

[[ -n "$SOURCE" && -d "$SOURCE" ]] || { echo "--source must be an existing directory" >&2; exit 2; }
[[ "$OUTPUT" == *.migration.tar.gz ]] || { echo "--output must end in .migration.tar.gz" >&2; exit 2; }
[[ ! -e "$OUTPUT" ]] || { echo "Refusing to overwrite: $OUTPUT" >&2; exit 1; }

SOURCE="$(cd "$SOURCE" && pwd)"
OUTPUT_DIR="$(cd "$(dirname "$OUTPUT")" && pwd)"
OUTPUT="${OUTPUT_DIR}/$(basename "$OUTPUT")"

excludes=(
  --exclude='.env'
  --exclude='.env.local'
  --exclude='.env.production'
  --exclude='.env.development'
  --exclude='config/paths.local.env'
  --exclude='.aws'
  --exclude='.git'
  --exclude='.venv'
  --exclude='venv'
  --exclude='__pycache__'
  --exclude='.pytest_cache'
  --exclude='*.pyc'
  --exclude='*.log'
  --exclude='.DS_Store'
)

if [[ $INCLUDE_DATA -eq 0 ]]; then
  excludes+=(--exclude='data' --exclude='review' --exclude='sr_output' --exclude='output')
  echo "Packaging code/config only; data and review outputs are excluded."
else
  echo "Including data and review outputs. Keep the archive on an approved local transfer medium."
fi

parent="$(dirname "$SOURCE")"
name="$(basename "$SOURCE")"
tar -C "$parent" "${excludes[@]}" -czf "$OUTPUT" "$name"

echo "Created: $OUTPUT"
echo "SHA-256: $(shasum -a 256 "$OUTPUT" | awk '{print $1}')"
echo "Note: this archive is not encrypted. Use AirDrop or an encrypted external drive."
