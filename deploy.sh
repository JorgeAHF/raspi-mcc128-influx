#!/usr/bin/env bash
set -e   # hace que el script se detenga si hay error

# Ruta al repo (ajústala si lo clonaste en otra carpeta)
cd ~/projects/raspi-mcc128-influx

echo "→ Actualizando código desde GitHub..."
git fetch --all
git reset --hard origin/main

echo "→ Activando entorno virtual..."
source ~/venv-daq/bin/activate

echo "→ Instalando dependencias..."
pip install -r requirements.txt

echo "→ Reiniciando servicio edge.service..."
sudo systemctl restart edge.service || true

echo "✅ Deploy terminado con éxito."
