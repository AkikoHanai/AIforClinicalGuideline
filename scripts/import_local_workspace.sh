#!/usr/bin/env bash
set -euo pipefail

ARCHIVE=""
DESTINATION=""
EXPECTED_SHA256=""

usage() {
  cat <<'EOF'
Usage:
  ./scripts/import_local_workspace.sh --archive FILE --destination DIR [--sha256 HASH]

Verifies and extracts a migration archive. The script rejects absolute paths,
parent-directory traversal and an existing top-level destination.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --archive) ARCHIVE="${2:-}"; shift 2 ;;
    --destination) DESTINATION="${2:-}"; shift 2 ;;
    --sha256) EXPECTED_SHA256="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

[[ -f "$ARCHIVE" ]] || { echo "--archive must be an existing file" >&2; exit 2; }
[[ "$ARCHIVE" == *.migration.tar.gz ]] || { echo "Archive must end in .migration.tar.gz" >&2; exit 2; }
[[ -n "$DESTINATION" ]] || { echo "--destination is required" >&2; exit 2; }

actual_sha256="$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')"
if [[ -n "$EXPECTED_SHA256" && "$actual_sha256" != "$EXPECTED_SHA256" ]]; then
  echo "SHA-256 mismatch; archive was not extracted" >&2
  exit 1
fi

entries="$(tar -tzf "$ARCHIVE")"
if printf '%s\n' "$entries" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
  echo "Unsafe archive path detected; archive was not extracted" >&2
  exit 1
fi

top_level="$(printf '%s\n' "$entries" | sed 's#^\./##' | cut -d/ -f1 | sed '/^$/d' | sort -u)"
if [[ "$(printf '%s\n' "$top_level" | wc -l | tr -d ' ')" != "1" ]]; then
  echo "Archive must contain exactly one top-level directory" >&2
  exit 1
fi

mkdir -p "$DESTINATION"
DESTINATION="$(cd "$DESTINATION" && pwd)"
if [[ -e "${DESTINATION}/${top_level}" ]]; then
  echo "Refusing to overwrite: ${DESTINATION}/${top_level}" >&2
  exit 1
fi

tar -C "$DESTINATION" -xzf "$ARCHIVE"
echo "Imported: ${DESTINATION}/${top_level}"
echo "SHA-256: ${actual_sha256}"
