#!/usr/bin/env bash
# Copie shared/bl_core (source de vérité) vers les deux applications.
# Équivalent bash de sync_shared.ps1 — à lancer depuis le dossier v3 :
#   ./tools/sync_shared.sh
set -euo pipefail
cd "$(dirname "$0")/.."
for app in app_creation app_administration; do
  cp shared/bl_core/*.py "src/$app/bl_core/"
  echo "bl_core -> src/$app/bl_core"
done
