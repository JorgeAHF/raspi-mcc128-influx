#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR="$SCRIPT_DIR"
SERVICE_USER=${EDGE_SERVICE_USER:-JJSI}
PYTHON_VENV=${EDGE_PYTHON_VENV:-/home/$SERVICE_USER/venv-daq}
ACQ_SERVICE=${EDGE_ACQUISITION_SERVICE:-edge.service}
WEBAPI_SERVICE=${EDGE_WEBAPI_SERVICE:-webapi.service}
LOG_DIR=${EDGE_LOG_DIR:-/var/log/edge}
WEBUI_DIR="$REPO_DIR/edge/webui"

cd "$REPO_DIR"

echo "→ Actualizando código desde GitHub..."
git fetch --all
git reset --hard origin/main

echo "→ Activando entorno virtual ($PYTHON_VENV)..."
source "$PYTHON_VENV/bin/activate"

echo "→ Instalando dependencias de Python..."
pip install -r requirements.txt

if command -v npm >/dev/null 2>&1; then
  echo "→ Instalando dependencias de Node.js..."
  cd "$WEBUI_DIR"
  npm install

  echo "→ Compilando la SPA..."
  npm run build
  cd "$REPO_DIR"
else
  echo "⚠️ npm no está disponible en PATH; omitiendo construcción de la SPA" >&2
fi

if [ -n "$LOG_DIR" ]; then
  echo "→ Creando directorio de logs en $LOG_DIR"
  sudo install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_USER" "$LOG_DIR"
fi

echo "→ Recargando units de systemd..."
sudo systemctl daemon-reload

echo "→ Reiniciando servicios..."
if [ -n "$ACQ_SERVICE" ]; then
  sudo systemctl restart "$ACQ_SERVICE" || true
fi
if [ -n "$WEBAPI_SERVICE" ]; then
  sudo systemctl restart "$WEBAPI_SERVICE" || true
fi

echo "✅ Deploy terminado con éxito."
