# raspi-mcc128-influx
Sistema de adquisición con Raspberry Pi 5, hat MCC 128 y envío a InfluxDB 2.x.

## Requisitos
- Raspberry Pi 5 con Raspberry Pi OS 64-bit y acceso a Internet.
- Hat MCC 128 correctamente montado y cableado en modo diferencial.
- Python 3.10 o superior con `python3-venv`, `pip`, `git` y `curl` instalados.
- InfluxDB 2.x accesible desde la red de la Pi (URL, organización, bucket y token válidos).
- Permisos de `sudo` para instalar dependencias del sistema y registrar servicios systemd.

## Crear el entorno virtual `~/venv-daq`
```bash
sudo apt update
sudo apt install -y python3-venv python3-pip git curl
python3 -m venv ~/venv-daq
source ~/venv-daq/bin/activate
python -m pip install --upgrade pip
```
> Siempre active el entorno (`source ~/venv-daq/bin/activate`) antes de trabajar con el proyecto.

## Instalación de dependencias
```bash
mkdir -p ~/projects
cd ~/projects
# clone o actualice el repositorio según corresponda
git clone https://github.com/<su-organizacion>/raspi-mcc128-influx.git
cd raspi-mcc128-influx
source ~/venv-daq/bin/activate
pip install -r requirements.txt
```

## Configuración de `.env` y `sensors.yaml`
### Credenciales de InfluxDB (`edge/.env`)
1. Copie el ejemplo y edítelo con sus valores reales:
   ```bash
   cd ~/projects/raspi-mcc128-influx/edge
   cp .env.example .env
   chmod 600 .env
   nano .env  # ajuste INFLUX_URL, INFLUX_ORG, INFLUX_BUCKET e INFLUX_TOKEN
   ```
2. Verifique las credenciales antes de iniciar el servicio:
   ```bash
   source ~/venv-daq/bin/activate
   export $(grep -v '^#' .env | xargs)
   curl --request GET "$INFLUX_URL/api/v2/buckets" \
        --header "Authorization: Token $INFLUX_TOKEN" \
        --header "Accept: application/json"
   ```
   Debe responder `200 OK`. Un `401` indica token/organización incorrectos.

### Sensores y adquisición (`edge/config/sensors.yaml`)
Ajuste los canales, nombres, unidades y calibraciones según su montaje. Ejemplo incluido:
```yaml
station_id: rpi5-a
sample_rate_hz: 10
scan_block_size: 50         # bloque de 5 s -> timeout dinámico = 5 s + 0.5 s de margen
channels:
  - ch: 0
    sensor: LVDT_P1
    unit: mm
    v_range: 10
    calib: {gain: 2.000, offset: -0.10}
  - ch: 1
    sensor: LVDT_P2
    unit: mm
    v_range: 10
    calib: {gain: 2.000, offset: 0.00}
```

| Parámetro                 | Ubicación                           | Valor por defecto | Descripción |
|---------------------------|-------------------------------------|-------------------|-------------|
| `sample_rate_hz`          | `edge/config/sensors.yaml`          | `10` Hz           | Frecuencia de muestreo por canal (`fs`). Ajuste según la dinámica del sensor y el ancho de banda requerido.【F:edge/config/sensors.yaml†L1-L12】 |
| `scan_block_size`         | `edge/config/sensors.yaml`          | `50` muestras     | Tamaño del bloque leído en cada iteración. Define la latencia (~5 s a 10 Hz) y se usa para calcular el timeout dinámico.【F:edge/config/sensors.yaml†L3-L8】【F:edge/src/mcc_reader.py†L8-L35】 |
| `DEFAULT_TIMEOUT_MARGIN_S`| `edge/src/mcc_reader.py`            | `0.5` s           | Margen extra sumado al tiempo esperado del bloque (`block_size/fs + margen`) para evitar timeouts espurios.【F:edge/src/mcc_reader.py†L21-L35】 |

## Guía de calibración (`gain` / `offset`)
- Cada canal aplica la relación lineal `magnitud = gain * Voltaje + offset` definida en `calib`.
- Para obtener `gain` y `offset`, registre dos o más puntos conocidos (por ejemplo, 0 % y 100 % de recorrido) y calcule la recta (pendiente = `gain`, intersección = `offset`).
- Actualice los valores en `sensors.yaml` y guarde. El módulo `calibrate.apply_calibration` aplicará automáticamente la corrección durante la adquisición.【F:edge/config/sensors.yaml†L6-L12】【F:edge/src/calibrate.py†L1-L3】

## Prueba rápida de lectura
Realice esta validación antes de instalar el servicio.
```bash
cd ~/projects/raspi-mcc128-influx/edge
source ~/venv-daq/bin/activate
python - <<'PY'
import sys, pathlib
sys.path.append(str(pathlib.Path('src').resolve()))
from mcc_reader import open_mcc128, start_scan, read_block
from daqhats import AnalogInputRange
cfg = {
    'channels': [0, 1],
    'fs': 10,
    'block': 10,
}
board = open_mcc128()
mask, block = start_scan(board, cfg['channels'], cfg['fs'], AnalogInputRange.BIP_10V, cfg['block'])
data = read_block(board, mask, block, cfg['channels'], sample_rate_hz=cfg['fs'])
print({ch: vals[:5] for ch, vals in data.items()})
board.a_in_scan_stop(); board.a_in_scan_cleanup()
PY
```
Espere una estructura `{canal: [valores...]}`. Presione `Ctrl+C` si necesita abortar.

Si desea enviar datos reales a Influx, ejecute el colector continuo (deténgalo con `Ctrl+C` cuando termine):
```bash
cd ~/projects/raspi-mcc128-influx/edge
source ~/venv-daq/bin/activate
python src/acquire.py
```

## Instalación del servicio `edge.service`
1. Ajuste rutas, usuario y entorno virtual en `edge/service/edge.service` según su sistema (edite `User`, `WorkingDirectory`, `EnvironmentFile` y `ExecStart`).【F:edge/service/edge.service†L1-L13】
2. Copie el archivo a systemd y recargue la configuración:
   ```bash
   sudo cp edge/service/edge.service /etc/systemd/system/edge.service
   sudo systemctl daemon-reload
   ```
3. Revise que las rutas apunten al repositorio y al entorno `~/venv-daq`.

## Habilitar y supervisar el servicio
```bash
sudo systemctl enable --now edge.service
sudo systemctl status edge.service --no-pager
```
Para aplicar cambios futuros (`.env`, `sensors.yaml` o código):
```bash
sudo systemctl daemon-reload      # si cambió el unit file
sudo systemctl restart edge.service
journalctl -u edge.service -f     # ver logs en vivo
```

## Validar conectividad desde la Pi
```bash
source ~/venv-daq/bin/activate
curl -f "$INFLUX_URL/health" || echo "Influx no responde"
```
Debe devolver `pass`. Si falla, verifique red/firewall y que la hora del sistema sea correcta (`timedatectl status`).

## Uso de `deploy.sh`
El script automatiza la actualización del código y la reinstalación de dependencias:
```bash
cd ~/projects/raspi-mcc128-influx
bash deploy.sh
```
Pasos internos: `git fetch/reset` a `origin/main`, activa `~/venv-daq`, instala `requirements.txt` y reinicia `edge.service`. Edite el script si su ruta o rama difiere.【F:deploy.sh†L1-L19】

## Solución de problemas comunes
- **InfluxDB responde 400 (Bad Request)**: revise que el bucket exista y que las etiquetas/campos no contengan caracteres no válidos. Verifique que el host no fuerce HTTPS cuando usa HTTP.【F:edge/src/sender.py†L46-L86】
- **InfluxDB responde 401 (Unauthorized)**: confirme `INFLUX_TOKEN`, `INFLUX_ORG` y permisos del token (`read/write` sobre el bucket). Repita la prueba `curl` de credenciales.
- **Cortafuegos / puertos bloqueados**: asegure que el puerto de Influx (por defecto 8086) esté abierto desde la red de la Pi (`sudo ufw allow out 8086/tcp` o regla equivalente en el servidor).
- **Desajuste horario / NTP**: la marca de tiempo se envía en nanosegundos. Configure NTP para evitar rechazos por timestamps futuros (`sudo timedatectl set-ntp true`).
- **Falta de variables de entorno al ejecutar como servicio**: revise que `EnvironmentFile` apunte al `.env` correcto y reinicie el servicio tras cambios.【F:edge/src/sender.py†L13-L55】【F:edge/service/edge.service†L7-L11】
- **Overflow del buffer del MCC 128**: aumente `scan_block_size`, reduzca `sample_rate_hz` o mejore la conectividad a Influx para evitar colas llenas. Revise los mensajes de advertencia en `journalctl`.
