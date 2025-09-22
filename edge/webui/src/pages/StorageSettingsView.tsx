import { ChangeEvent } from "react";
import { SectionCard } from "../components/SectionCard";
import { SinkToggle } from "../components/SinkToggle";
import { StorageSettings } from "../types";

interface StorageSettingsViewProps {
  settings: StorageSettings | null;
  onChange: (settings: StorageSettings) => void;
  onSubmit: () => void;
  onRefresh: () => void;
  dirty: boolean;
  saving: boolean;
  loading: boolean;
}

export function StorageSettingsView({
  settings,
  onChange,
  onSubmit,
  onRefresh,
  dirty,
  saving,
  loading,
}: StorageSettingsViewProps) {
  const handleChange = (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    if (!settings) return;
    const { name, value, checked } = event.target as HTMLInputElement;
    const next: StorageSettings = { ...settings };
    if (name === "verify_ssl") {
      next.verify_ssl = checked;
    } else if (name === "driver" || name === "url" || name === "org" || name === "bucket" || name === "token") {
      (next as any)[name] = value;
    } else if (name === "batch_size" || name === "queue_max_size") {
      const parsed = Number.parseInt(value, 10);
      if (Number.isNaN(parsed)) {
        return;
      }
      (next as any)[name] = parsed;
    } else if (name === "timeout_s") {
      const parsed = Number.parseFloat(value);
      if (Number.isNaN(parsed)) {
        return;
      }
      next.timeout_s = parsed;
    }
    onChange(next);
  };

  const handleRetryChange = (event: ChangeEvent<HTMLInputElement>) => {
    if (!settings) return;
    const { name, value } = event.target;
    const retry = { ...settings.retry };
    if (name === "max_attempts") {
      const parsed = Number.parseInt(value, 10);
      if (Number.isNaN(parsed)) {
        return;
      }
      retry.max_attempts = parsed;
    } else if (name === "base_delay_s") {
      const parsed = Number.parseFloat(value);
      if (Number.isNaN(parsed)) {
        return;
      }
      retry.base_delay_s = parsed;
    } else if (name === "max_backoff_s") {
      if (value === "") {
        retry.max_backoff_s = null;
      } else {
        const parsed = Number.parseFloat(value);
        if (Number.isNaN(parsed)) {
          return;
        }
        retry.max_backoff_s = parsed;
      }
    }
    onChange({ ...settings, retry });
  };

  const handleCsvChange = (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    if (!settings) return;
    const { name, value, checked } = event.target as HTMLInputElement;
    const csv = { ...settings.csv };
    if (name === "rotation") {
      csv.rotation = value as typeof csv.rotation;
    } else if (name === "write_headers") {
      csv.write_headers = checked;
    } else {
      (csv as any)[name] = value;
    }
    onChange({ ...settings, csv });
  };

  const handleFtpChange = (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    if (!settings) return;
    const { name, value, checked } = event.target as HTMLInputElement;
    const ftp = { ...settings.ftp };
    if (name === "protocol") {
      ftp.protocol = value as typeof ftp.protocol;
    } else if (name === "passive") {
      ftp.passive = checked;
    } else if (name === "port") {
      if (value === "") {
        ftp.port = null;
      } else {
        const parsed = Number.parseInt(value, 10);
        if (Number.isNaN(parsed)) {
          return;
        }
        ftp.port = parsed;
      }
    } else if (name === "upload_interval_s") {
      if (value === "") {
        ftp.upload_interval_s = null;
      } else {
        const parsed = Number.parseFloat(value);
        if (Number.isNaN(parsed)) {
          return;
        }
        ftp.upload_interval_s = parsed;
      }
    } else {
      (ftp as any)[name] = value === "" ? null : value;
    }
    onChange({ ...settings, ftp });
  };

  const handleSinkToggle = (sink: string, enabled: boolean) => {
    if (!settings) return;
    if (sink === settings.driver && !enabled) {
      alert("El driver principal no se puede deshabilitar.");
      return;
    }
    const sinks = updateSinks(settings.sinks, sink, enabled);
    if (sink === "csv") {
      onChange({ ...settings, sinks, csv: { ...settings.csv, enabled } });
    } else if (sink === "ftp") {
      onChange({ ...settings, sinks, ftp: { ...settings.ftp, enabled } });
    } else {
      onChange({ ...settings, sinks });
    }
  };

  const updateSinks = (current: string[], sink: string, enabled: boolean) => {
    const set = new Set(current);
    if (enabled) {
      set.add(sink);
    } else {
      set.delete(sink);
    }
    return Array.from(set);
  };

  return (
    <SectionCard
      id="storage"
      title="Almacenamiento"
      description="Configura InfluxDB y sinks secundarios como CSV o FTP."
      actions={
        <div className="actions">
          <button type="button" className="secondary" onClick={onRefresh} disabled={loading || saving}>
            Recargar
          </button>
          <button type="button" onClick={onSubmit} disabled={!dirty || saving || !settings}>
            {saving ? "Guardando…" : "Guardar"}
          </button>
        </div>
      }
    >
      {!settings ? (
        <p>{loading ? "Cargando configuración…" : "No hay configuración de almacenamiento."}</p>
      ) : (
        <form className="form-grid" onSubmit={(event) => event.preventDefault()}>
          <fieldset>
            <legend>InfluxDB</legend>
            <div className="grid-columns">
              <label>
                <span>Driver</span>
                <input type="text" name="driver" value={settings.driver} onChange={handleChange} />
              </label>
              <label>
                <span>URL</span>
                <input type="url" name="url" value={settings.url} onChange={handleChange} required />
              </label>
              <label>
                <span>Organización</span>
                <input type="text" name="org" value={settings.org} onChange={handleChange} required />
              </label>
              <label>
                <span>Bucket</span>
                <input type="text" name="bucket" value={settings.bucket} onChange={handleChange} required />
              </label>
            </div>
            <label>
              <span>Token</span>
              <input type="password" name="token" value={settings.token} onChange={handleChange} required />
            </label>
            <div className="grid-columns">
              <label>
                <span>Batch size</span>
                <input type="number" name="batch_size" min="1" value={settings.batch_size} onChange={handleChange} />
              </label>
              <label>
                <span>Timeout (s)</span>
                <input type="number" name="timeout_s" min="0" step="0.1" value={settings.timeout_s} onChange={handleChange} />
              </label>
              <label>
                <span>Queue max</span>
                <input type="number" name="queue_max_size" min="1" value={settings.queue_max_size} onChange={handleChange} />
              </label>
              <label className="checkbox">
                <input type="checkbox" name="verify_ssl" checked={settings.verify_ssl} onChange={handleChange} />
                <span>Verificar SSL</span>
              </label>
            </div>
          </fieldset>

          <fieldset>
            <legend>Reintentos</legend>
            <div className="grid-columns">
              <label>
                <span>Máx. intentos</span>
                <input type="number" name="max_attempts" min="1" value={settings.retry.max_attempts} onChange={handleRetryChange} />
              </label>
              <label>
                <span>Delay base (s)</span>
                <input type="number" name="base_delay_s" min="0" step="0.1" value={settings.retry.base_delay_s} onChange={handleRetryChange} />
              </label>
              <label>
                <span>Backoff máx. (s)</span>
                <input
                  type="number"
                  name="max_backoff_s"
                  min="0"
                  step="0.1"
                  value={settings.retry.max_backoff_s ?? ""}
                  onChange={handleRetryChange}
                />
              </label>
            </div>
          </fieldset>

          <fieldset>
            <legend>Sinks activos</legend>
            <div className="sinks-grid">
              <SinkToggle sink={settings.driver} label="Influx" enabled={true} onToggle={() => null} disabled />
              <SinkToggle sink="csv" label="CSV" enabled={settings.csv.enabled} onToggle={handleSinkToggle} />
              <SinkToggle sink="ftp" label="FTP" enabled={settings.ftp.enabled} onToggle={handleSinkToggle} />
            </div>
          </fieldset>

          <fieldset disabled={!settings.csv.enabled}>
            <legend>CSV</legend>
            <div className="grid-columns">
              <label>
                <span>Directorio</span>
                <input type="text" name="directory" value={settings.csv.directory} onChange={handleCsvChange} />
              </label>
              <label>
                <span>Rotación</span>
                <select name="rotation" value={settings.csv.rotation} onChange={handleCsvChange}>
                  <option value="session">Por sesión</option>
                  <option value="daily">Diaria</option>
                </select>
              </label>
              <label>
                <span>Prefijo</span>
                <input type="text" name="filename_prefix" value={settings.csv.filename_prefix} onChange={handleCsvChange} />
              </label>
            </div>
            <div className="grid-columns">
              <label>
                <span>Formato timestamp</span>
                <input type="text" name="timestamp_format" value={settings.csv.timestamp_format} onChange={handleCsvChange} />
              </label>
              <label>
                <span>Delimitador</span>
                <input type="text" name="delimiter" value={settings.csv.delimiter} onChange={handleCsvChange} />
              </label>
              <label>
                <span>Decimal</span>
                <input type="text" name="decimal" value={settings.csv.decimal} onChange={handleCsvChange} />
              </label>
              <label>
                <span>Encoding</span>
                <input type="text" name="encoding" value={settings.csv.encoding} onChange={handleCsvChange} />
              </label>
            </div>
            <label>
              <span>Salto de línea</span>
              <input type="text" name="newline" value={settings.csv.newline} onChange={handleCsvChange} />
            </label>
            <label className="checkbox">
              <input type="checkbox" name="write_headers" checked={settings.csv.write_headers} onChange={handleCsvChange} />
              <span>Incluir cabeceras</span>
            </label>
          </fieldset>

          <fieldset disabled={!settings.ftp.enabled}>
            <legend>FTP / SFTP</legend>
            <div className="grid-columns">
              <label>
                <span>Protocolo</span>
                <select name="protocol" value={settings.ftp.protocol} onChange={handleFtpChange}>
                  <option value="ftp">FTP</option>
                  <option value="sftp">SFTP</option>
                </select>
              </label>
              <label>
                <span>Host</span>
                <input type="text" name="host" value={settings.ftp.host ?? ""} onChange={handleFtpChange} />
              </label>
              <label>
                <span>Puerto</span>
                <input type="number" name="port" value={settings.ftp.port ?? ""} onChange={handleFtpChange} />
              </label>
              <label>
                <span>Usuario</span>
                <input type="text" name="username" value={settings.ftp.username ?? ""} onChange={handleFtpChange} />
              </label>
              <label>
                <span>Contraseña</span>
                <input type="password" name="password" value={settings.ftp.password ?? ""} onChange={handleFtpChange} />
              </label>
            </div>
            <div className="grid-columns">
              <label>
                <span>Directorio remoto</span>
                <input type="text" name="remote_dir" value={settings.ftp.remote_dir} onChange={handleFtpChange} />
              </label>
              <label>
                <span>Directorio local</span>
                <input type="text" name="local_dir" value={settings.ftp.local_dir ?? ""} onChange={handleFtpChange} />
              </label>
              <label>
                <span>Rotación</span>
                <select name="rotation" value={settings.ftp.rotation} onChange={handleFtpChange}>
                  <option value="session">Por sesión</option>
                  <option value="periodic">Periódica</option>
                </select>
              </label>
              <label>
                <span>Intervalo subida (s)</span>
                <input type="number" name="upload_interval_s" min="0" step="0.1" value={settings.ftp.upload_interval_s ?? ""} onChange={handleFtpChange} />
              </label>
              <label className="checkbox">
                <input type="checkbox" name="passive" checked={settings.ftp.passive} onChange={handleFtpChange} />
                <span>Pasivo</span>
              </label>
            </div>
          </fieldset>
        </form>
      )}
      {dirty && <p className="muted">Hay cambios sin guardar.</p>}
    </SectionCard>
  );
}
