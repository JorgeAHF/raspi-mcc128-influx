#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DIST_DIR="$ROOT_DIR/dist"
TARGET_DIR="${DEPLOY_WEBUI_TARGET:-/var/www/edge-webui}"
SYSTEMD_SERVICE="${DEPLOY_SYSTEMD_SERVICE:-edge.service}"
NGINX_SERVICE="${DEPLOY_NGINX_SERVICE:-nginx}"

if [ ! -d "$DIST_DIR" ]; then
  echo "⚠️ El directorio dist no existe. Ejecuta 'npm run build' primero." >&2
  exit 1
fi

echo "→ Copiando artefactos a $TARGET_DIR"
sudo mkdir -p "$TARGET_DIR"
sudo rsync -a --delete "$DIST_DIR"/ "$TARGET_DIR"/

echo "→ Recargando servicios"
if [ -n "$SYSTEMD_SERVICE" ]; then
  sudo systemctl reload "$SYSTEMD_SERVICE" 2>/dev/null || sudo systemctl restart "$SYSTEMD_SERVICE" || true
fi
if [ -n "$NGINX_SERVICE" ]; then
  sudo systemctl reload "$NGINX_SERVICE" || true
fi

echo "✅ Despliegue completado"
