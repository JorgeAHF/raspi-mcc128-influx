# raspi-mcc128-influx
DAQ RBP5 with MCC128 to InfluxDB

## Configuración de credenciales de InfluxDB

1. Copie `edge/.env.example` a `edge/.env` y complete sus valores reales de InfluxDB.
2. Verifique las credenciales antes de iniciar el servicio:
   ```bash
   curl --request GET "$INFLUX_URL/api/v2/buckets" \
     --header "Authorization: Token $INFLUX_TOKEN" \
     --header "Accept: application/json"
   ```
   La llamada debe devolver 200 OK si `INFLUX_URL` e `INFLUX_TOKEN` son correctos.
3. Asegure los permisos del archivo con `chmod 600 edge/.env`.
4. Recargue el servicio con `sudo systemctl restart edge.service` para que systemd lea las nuevas variables.
