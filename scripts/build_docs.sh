#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
README_FILE="${ROOT_DIR}/README.md"
ASSET_DIR="${ROOT_DIR}/docs/assets"
INGEST_FILE="${ROOT_DIR}/examples/search/ingest.bpg.yaml"
HTML_FILE="${ASSET_DIR}/ingest.bpg.html"
PNG_FILE="${ASSET_DIR}/search-ingest-pipeline.png"

if [[ ! -f "${README_FILE}" ]]; then
  echo "README.md not found at ${README_FILE}" >&2
  exit 1
fi

if [[ ! -f "${INGEST_FILE}" ]]; then
  echo "Ingest YAML not found at ${INGEST_FILE}" >&2
  exit 1
fi

if ! command -v google-chrome >/dev/null 2>&1; then
  echo "google-chrome is required for docs image generation." >&2
  exit 1
fi

cd "${ROOT_DIR}"
mkdir -p "${ASSET_DIR}"

uv run bpg visualize examples/search/ingest.bpg.yaml --output-dir docs/assets

google-chrome --headless --disable-gpu \
  --screenshot="${PNG_FILE}" \
  --window-size=1200,900 \
  "file://${HTML_FILE}"

TMP_BLOCK="$(mktemp)"
TMP_README="$(mktemp)"
trap 'rm -f "${TMP_BLOCK}" "${TMP_README}"' EXIT

{
  echo "<!-- BEGIN:search-ingest-yaml -->"
  echo '```yaml'
  cat "${INGEST_FILE}"
  echo '```'
  echo "<!-- END:search-ingest-yaml -->"
} > "${TMP_BLOCK}"

if ! grep -q "<!-- BEGIN:search-ingest-yaml -->" "${README_FILE}"; then
  echo "README is missing BEGIN marker: <!-- BEGIN:search-ingest-yaml -->" >&2
  exit 1
fi
if ! grep -q "<!-- END:search-ingest-yaml -->" "${README_FILE}"; then
  echo "README is missing END marker: <!-- END:search-ingest-yaml -->" >&2
  exit 1
fi

awk '
  BEGIN {
    in_block = 0
    replacement_file = ARGV[1]
    while ((getline line < replacement_file) > 0) {
      replacement = replacement line "\n"
    }
    close(replacement_file)
    ARGV[1] = ""
  }
  /<!-- BEGIN:search-ingest-yaml -->/ {
    printf "%s", replacement
    in_block = 1
    next
  }
  /<!-- END:search-ingest-yaml -->/ {
    in_block = 0
    next
  }
  {
    if (!in_block) print
  }
' "${TMP_BLOCK}" "${README_FILE}" > "${TMP_README}"

mv "${TMP_README}" "${README_FILE}"
echo "Docs build complete: ${PNG_FILE}, README YAML block refreshed."
