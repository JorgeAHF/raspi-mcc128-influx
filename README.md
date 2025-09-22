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

## Configuración de `storage.yaml` y `sensors.yaml`
### Migración automática desde `.env`
Si ya tiene una instalación anterior basada en variables de entorno, ejecute el migrador para convertir los archivos existentes al nuevo esquema tipado:

```bash
cd ~/projects/raspi-mcc128-influx
source ~/venv-daq/bin/activate
python -m edge.config.migrate
```

El script reescribe `edge/config/sensors.yaml` con la nueva estructura y genera `edge/config/storage.yaml` a partir de las variables `INFLUX_*` definidas en `edge/.env` (si existen). Puede ejecutarlo tantas veces como quiera; si los archivos ya cumplen el nuevo formato no realizará cambios.

### Credenciales de InfluxDB (`edge/config/storage.yaml`)
1. Abra el archivo y complete los campos con sus valores reales:
   ```bash
   cd ~/projects/raspi-mcc128-influx/edge
   nano config/storage.yaml  # ajuste url, org, bucket y token
   ```
2. Proteja las credenciales restringiendo los permisos:
   ```bash
   chmod 600 config/storage.yaml
   ```
3. Verifique la conectividad antes de iniciar el servicio:
   ```bash
   source ~/venv-daq/bin/activate
   python - <<'PY'
   from edge.config import load_storage_settings
   cfg = load_storage_settings()
   import requests
   resp = requests.get(f"{cfg.url.rstrip('/')}/api/v2/buckets", headers={"Authorization": f"Token {cfg.token}"})
   print(resp.status_code)
   PY
   ```
   Debe imprimir `200`. Un `401` indica token/organización incorrectos.

> **Importante:** `config/storage.yaml` contiene secretos. Evite subir los cambios al repositorio público y haga un respaldo seguro si necesita compartir el código.

### Rotación del token de InfluxDB
1. Inicie sesión en la UI de InfluxDB y genere un token nuevo con permisos de lectura/escritura sobre el bucket correspondiente.
2. Actualice los campos de `config/storage.yaml` que hayan cambiado (`token`, `bucket`, etc.) y guarde el archivo.
3. Reinicie el servicio o proceso que use estas credenciales:
   ```bash
   sudo systemctl restart edge.service
   ```
4. Una vez validado el funcionamiento, revoque el token anterior desde la UI de InfluxDB para evitar usos no autorizados.

### Sensores y adquisición (`edge/config/sensors.yaml`)
Ajuste los canales, nombres, unidades y calibraciones según su montaje. Ejemplo incluido:
```yaml
station_id: rpi5-a
acquisition:
  sample_rate_hz: 10
  block_size: 50         # bloque de 5 s -> timeout dinámico = 5 s + 0.5 s de margen
  duration_s:
  total_samples:
  drift_detection:
    correction_threshold_ns: 2000000   # corrige derivas mayores a 2 ms
channels:
  - index: 0
    name: LVDT_P1
    unit: mm
    voltage_range: 10.0
    calibration: {gain: 2.000, offset: -0.10}
  - index: 1
    name: LVDT_P2
    unit: mm
    voltage_range: 10.0
    calibration: {gain: 2.000, offset: 0.00}
```

> **Nota:** la MCC128 aplica un único rango de entrada para todos los canales
> habilitados. Configure el mismo `voltage_range` en cada canal; de lo
> contrario la inicialización fallará con un error explicando la
> limitación.【F:edge/scr/mcc_reader.py†L1-L71】

| Parámetro                 | Ubicación                           | Valor por defecto | Descripción |
|---------------------------|-------------------------------------|-------------------|-------------|
| `acquisition.sample_rate_hz` | `edge/config/sensors.yaml`       | `10` Hz           | Frecuencia de muestreo por canal (`fs`). Ajuste según la dinámica del sensor y el ancho de banda requerido.【F:edge/config/sensors.yaml†L1-L18】 |
| `acquisition.block_size`  | `edge/config/sensors.yaml`          | `50` muestras     | Tamaño del bloque leído en cada iteración. Define la latencia (~5 s a 10 Hz) y se usa para calcular el timeout dinámico.【F:edge/config/sensors.yaml†L1-L18】【F:edge/scr/mcc_reader.py†L52-L94】 |
| `acquisition.total_samples` | `edge/config/sensors.yaml`        | `null`            | Presupuesto máximo de muestras por canal. Activa el modo `timed` y detiene la adquisición tras alcanzarlo.【F:edge/config/sensors.yaml†L1-L18】【F:edge/scr/acquisition.py†L68-L126】 |
| `acquisition.drift_detection.correction_threshold_ns` | `edge/config/sensors.yaml` | `2_000_000` ns | Umbral opcional para realinear el acumulador de timestamps con el reloj del sistema cuando la deriva supera ese valor.【F:edge/config/sensors.yaml†L1-L18】【F:edge/scr/acquisition.py†L68-L126】 |
| `DEFAULT_TIMEOUT_MARGIN_S`| `edge/scr/mcc_reader.py`            | `0.5` s           | Margen extra sumado al tiempo esperado del bloque (`block_size/fs + margen`) para evitar timeouts espurios.【F:edge/scr/mcc_reader.py†L19-L35】 |

## Monitoreo de jitter y deriva
- El colector asigna timestamps consecutivos a cada muestra con un acumulador `next_ts_ns`, evitando recalcularlos a partir del reloj en cada bloque y eliminando el jitter intra-bloque.【F:edge/scr/acquire.py†L1-L97】
- Tras cada lectura se registra en `INFO` la desviación máxima observada entre el último timestamp del bloque y el reloj del sistema (`Bloque con ...; desviación máxima ...`). Valores pequeños (p. ej. <1 ms) indican latencias estables; si aumentan, conviene revisar carga de CPU o bloqueos de I/O.【F:edge/scr/acquire.py†L67-L97】
- Cuando `drift_detection.correction_threshold_ns` está definido y la deriva supera ese umbral, se alinea el acumulador con `time_ns()` y se anota un `DEBUG` con el ajuste aplicado, lo que evita que los timestamps se desfasen progresivamente.【F:edge/config/sensors.yaml†L3-L9】【F:edge/scr/acquire.py†L48-L96】


## Guía de calibración (`gain` / `offset`)
- Cada canal aplica la relación lineal `magnitud = gain * Voltaje + offset` definida en `calib`.
- Para obtener `gain` y `offset`, registre dos o más puntos conocidos (por ejemplo, 0 % y 100 % de recorrido) y calcule la recta (pendiente = `gain`, intersección = `offset`).
- Actualice los valores en `sensors.yaml` y guarde. El módulo `calibrate.apply_calibration` aplicará automáticamente la corrección durante la adquisición.【F:edge/config/sensors.yaml†L6-L12】【F:edge/scr/calibrate.py†L1-L4】

## Prueba rápida de lectura
Realice esta validación antes de instalar el servicio.
```bash
cd ~/projects/raspi-mcc128-influx/edge
source ~/venv-daq/bin/activate
python - <<'PY'
import sys, pathlib
sys.path.append(str(pathlib.Path('scr').resolve()))
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
python scr/acquire.py
```

## Modo test y vista previa web
- Ejecute el `AcquisitionRunner` con `mode="test"` para omitir los sinks de almacenamiento y publicar cada bloque calibrado en un canal de broadcast (por ejemplo un `asyncio.Queue`).【F:edge/scr/acquisition.py†L118-L197】
- El helper `stream_preview` de `edge/scr/preview.py` consume esa cola y genera un async iterable listo para la API web, aplicando filtros de canales, duración y un `downsample` configurable para reducir ancho de banda.【F:edge/scr/preview.py†L1-L134】
- Limite el `downsample` y la duración (`max_duration_s`) según lo solicitado por el cliente; se reutilizan los mismos índices de canal definidos en `sensors.yaml`, y se validan contra la configuración vigente.【F:edge/scr/preview.py†L26-L75】【F:edge/config/sensors.yaml†L1-L18】
- **Limitaciones:** el modo test no inicializa sinks pesados (Influx/CSV/FTP) para evitar contención con almacenamiento concurrente. Si necesita almacenar y previsualizar simultáneamente, ejecute instancias separadas o utilice colas con backpressure controlado.【F:edge/scr/acquisition.py†L134-L150】
- Métricas en logs: se informa cada bloque emitido (`DEBUG`) y un resumen al finalizar (`INFO`) con bloques y muestras entregadas, útil para monitorear latencias y tamaño de cola.【F:edge/scr/acquisition.py†L211-L253】

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
Para aplicar cambios futuros (`storage.yaml`, `sensors.yaml` o código):
```bash
sudo systemctl daemon-reload      # si cambió el unit file
sudo systemctl restart edge.service
journalctl -u edge.service -f     # ver logs en vivo
```

## Validar conectividad desde la Pi
```bash
source ~/venv-daq/bin/activate
python - <<'PY'
from edge.config import load_storage_settings
import requests
cfg = load_storage_settings()
resp = requests.get(f"{cfg.url.rstrip('/')}/health", timeout=5)
print(resp.json())
PY
```
Debe devolver `{"status": "pass"}`. Si falla, verifique red/firewall y que la hora del sistema sea correcta (`timedatectl status`).

## Uso de `deploy.sh`
El script automatiza la actualización del código y la reinstalación de dependencias:
```bash
cd ~/projects/raspi-mcc128-influx
bash deploy.sh
```
Pasos internos: `git fetch/reset` a `origin/main`, activa `~/venv-daq`, instala `requirements.txt` y reinicia `edge.service`. Edite el script si su ruta o rama difiere.【F:deploy.sh†L1-L19】

## Solución de problemas comunes
- **InfluxDB responde 400 (Bad Request)**: revise que el bucket exista y que las etiquetas/campos no contengan caracteres no válidos. Verifique que el host no fuerce HTTPS cuando usa HTTP.【F:edge/scr/sender.py†L46-L74】
- **InfluxDB responde 401 (Unauthorized)**: confirme `INFLUX_TOKEN`, `INFLUX_ORG` y permisos del token (`read/write` sobre el bucket). Repita la prueba `curl` de credenciales.
- **Cortafuegos / puertos bloqueados**: asegure que el puerto de Influx (por defecto 8086) esté abierto desde la red de la Pi (`sudo ufw allow out 8086/tcp` o regla equivalente en el servidor).
- **Desajuste horario / NTP**: la marca de tiempo se envía en nanosegundos. Configure NTP para evitar rechazos por timestamps futuros (`sudo timedatectl set-ntp true`).
- **storage.yaml incompleto al ejecutar como servicio**: verifique que `edge/config/storage.yaml` contenga las credenciales correctas y que el servicio tenga permisos de lectura antes de reiniciarlo.【F:edge/config/storage.yaml†L1-L14】【F:edge/scr/sender.py†L24-L152】
- **Overflow del buffer del MCC 128**: aumente `scan_block_size`, reduzca `sample_rate_hz` o mejore la conectividad a Influx para evitar colas llenas. Revise los mensajes de advertencia en `journalctl`.
