#!/bin/bash
# Verifica que cada getElementById('xyz') en JS apunte a un id="xyz" definido en HTML.
# Uso: bash check-ids.sh

set -e

cd "$(dirname "$0")/../../../.."

for html in index.html admin.html; do
  if [ ! -f "$html" ]; then
    echo "skip $html (no existe)"
    continue
  fi
  echo "=== $html ==="

  ids_def=$(grep -oE "id=\"[a-z][a-z0-9-]*\"" "$html" | sed 's/id="//;s/"//' | sort -u)

  # Refs en este HTML + JS asociados
  if [ "$html" = "index.html" ]; then
    js_files="common.js"
  else
    js_files="common.js"
  fi
  refs=$(grep -hoE "getElementById\(['\"][^'\"]+['\"]\)" "$html" $js_files 2>/dev/null \
    | sed "s/getElementById([\"']//;s/[\"'])//" | sort -u)

  missing=""
  for r in $refs; do
    if ! echo "$ids_def" | grep -qx "$r"; then
      missing="$missing $r"
    fi
  done

  if [ -z "$missing" ]; then
    echo "  OK — todos los getElementById tienen su id"
  else
    echo "  MISSING:"
    for m in $missing; do
      echo "    - $m"
    done
  fi
done
