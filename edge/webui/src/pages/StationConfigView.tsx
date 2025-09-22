import { ChangeEvent } from "react";
import { CalibrationInput } from "../components/CalibrationInput";
import { SectionCard } from "../components/SectionCard";
import { VoltageRangeSelect } from "../components/VoltageRangeSelect";
import { StationConfig } from "../types";

interface StationConfigViewProps {
  config: StationConfig | null;
  onChange: (config: StationConfig) => void;
  onSubmit: () => void;
  onRefresh: () => void;
  dirty: boolean;
  saving: boolean;
  loading: boolean;
}

export function StationConfigView({
  config,
  onChange,
  onSubmit,
  onRefresh,
  dirty,
  saving,
  loading,
}: StationConfigViewProps) {
  const handleMetaChange = (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    if (!config) return;
    const { name, value } = event.target;
    if (name === "description") {
      onChange({ ...config, description: value.trim() ? value : null });
    } else {
      onChange({ ...config, [name]: value });
    }
  };

  const handleAcquisitionChange = (event: ChangeEvent<HTMLInputElement>) => {
    if (!config) return;
    const { name, value } = event.target;
    const parsed = value === "" ? null : Number.parseFloat(value);
    if (value !== "" && !Number.isFinite(parsed)) {
      return;
    }
    const acquisition = { ...config.acquisition } as StationConfig["acquisition"] & Record<string, unknown>;
    if (name === "sample_rate_hz" && parsed !== null) {
      acquisition.sample_rate_hz = parsed;
    } else if (name === "block_size" && parsed !== null) {
      acquisition.block_size = parsed;
    } else if (name === "duration_s") {
      acquisition.duration_s = parsed;
    } else if (name === "total_samples") {
      acquisition.total_samples = parsed === null ? null : Math.trunc(parsed);
    } else if (name === "correction_threshold_ns") {
      const drift = { ...config.acquisition.drift_detection };
      if (parsed === null) {
        drift.correction_threshold_ns = null;
      } else if (Number.isFinite(parsed)) {
        drift.correction_threshold_ns = Math.trunc(parsed);
      }
      acquisition.drift_detection = drift;
    }
    onChange({ ...config, acquisition } as StationConfig);
  };

  const handleChannelChange = (index: number, field: string, value: unknown) => {
    if (!config) return;
    if (field === "index" && typeof value === "number" && Number.isNaN(value)) {
      return;
    }
    const channels = config.channels.map((channel, i) =>
      i === index
        ? {
            ...channel,
            [field]: value,
          }
        : channel,
    );
    onChange({ ...config, channels });
  };

  const handleAddChannel = () => {
    if (!config) return;
    const nextIndex =
      config.channels.reduce((max, channel) => Math.max(max, channel.index), -1) + 1;
    const newChannel = {
      index: nextIndex,
      name: `Canal ${nextIndex}`,
      unit: "V",
      voltage_range: 10,
      calibration: { gain: 1, offset: 0 },
    };
    onChange({ ...config, channels: [...config.channels, newChannel] });
  };

  const handleRemoveChannel = (idx: number) => {
    if (!config) return;
    const target = config.channels[idx];
    if (!confirm(`¿Eliminar canal ${target?.name ?? idx}?`)) {
      return;
    }
    onChange({ ...config, channels: config.channels.filter((_, i) => i !== idx) });
  };

  return (
    <SectionCard
      id="station"
      title="Configuración MCC128"
      description="Define canales, calibraciones y parámetros de adquisición."
      actions={
        <div className="actions">
          <button type="button" className="secondary" onClick={onRefresh} disabled={loading || saving}>
            Recargar
          </button>
          <button type="button" onClick={onSubmit} disabled={!dirty || saving || !config}>
            {saving ? "Guardando…" : "Guardar"}
          </button>
        </div>
      }
    >
      {!config ? (
        <p>{loading ? "Cargando configuración…" : "No hay datos de estación disponibles."}</p>
      ) : (
        <form className="form-grid" onSubmit={(event) => event.preventDefault()}>
          <div className="grid-columns">
            <label>
              <span>ID de estación</span>
              <input
                type="text"
                name="station_id"
                value={config.station_id}
                onChange={handleMetaChange}
                required
              />
            </label>
            <label>
              <span>Descripción</span>
              <input
                type="text"
                name="description"
                value={config.description ?? ""}
                onChange={handleMetaChange}
                placeholder="Opcional"
              />
            </label>
          </div>

          <fieldset>
            <legend>Adquisición</legend>
            <div className="grid-columns">
              <label>
                <span>Sample rate (Hz)</span>
                <input
                  type="number"
                  name="sample_rate_hz"
                  min="1"
                  step="0.1"
                  value={config.acquisition.sample_rate_hz}
                  onChange={handleAcquisitionChange}
                  required
                />
              </label>
              <label>
                <span>Block size</span>
                <input
                  type="number"
                  name="block_size"
                  min="1"
                  step="1"
                  value={config.acquisition.block_size}
                  onChange={handleAcquisitionChange}
                  required
                />
              </label>
              <label>
                <span>Duración (s)</span>
                <input
                  type="number"
                  name="duration_s"
                  min="0"
                  step="0.1"
                  value={config.acquisition.duration_s ?? ""}
                  onChange={handleAcquisitionChange}
                />
              </label>
              <label>
                <span>Total samples</span>
                <input
                  type="number"
                  name="total_samples"
                  min="0"
                  step="1"
                  value={config.acquisition.total_samples ?? ""}
                  onChange={handleAcquisitionChange}
                />
              </label>
              <label>
                <span>Corrección drift (ns)</span>
                <input
                  type="number"
                  name="correction_threshold_ns"
                  min="0"
                  step="1"
                  value={config.acquisition.drift_detection.correction_threshold_ns ?? ""}
                  onChange={handleAcquisitionChange}
                />
              </label>
            </div>
          </fieldset>

          <div className="channels-header">
            <h3>Canales configurados</h3>
            <button type="button" className="secondary" onClick={handleAddChannel}>
              Añadir canal
            </button>
          </div>

          <div className="channels-list">
            {config.channels.map((channel, idx) => (
              <div key={`${channel.index}-${idx}`} className="channel-card">
                <div className="channel-title">
                  <h4>
                    #{channel.index} · {channel.name}
                  </h4>
                  <button
                    type="button"
                    className="danger"
                    onClick={() => handleRemoveChannel(idx)}
                    title="Eliminar canal"
                  >
                    Eliminar
                  </button>
                </div>
                <div className="grid-columns">
                  <label>
                    <span>Índice</span>
                    <input
                      type="number"
                      value={channel.index}
                      min={0}
                      step={1}
                      onChange={(event) => handleChannelChange(idx, "index", Number.parseInt(event.target.value, 10))}
                    />
                  </label>
                  <label>
                    <span>Nombre</span>
                    <input
                      type="text"
                      value={channel.name}
                      onChange={(event) => handleChannelChange(idx, "name", event.target.value)}
                    />
                  </label>
                  <label>
                    <span>Unidad</span>
                    <input
                      type="text"
                      value={channel.unit}
                      onChange={(event) => handleChannelChange(idx, "unit", event.target.value)}
                    />
                  </label>
                </div>
                <label className="voltage-field">
                  <span>Rango de voltaje</span>
                  <VoltageRangeSelect
                    value={channel.voltage_range}
                    onChange={(value) => handleChannelChange(idx, "voltage_range", value)}
                  />
                </label>
                <div>
                  <span>Calibración</span>
                  <CalibrationInput
                    value={channel.calibration}
                    onChange={(value) => handleChannelChange(idx, "calibration", value)}
                  />
                </div>
              </div>
            ))}
            {config.channels.length === 0 && <p>No hay canales configurados.</p>}
          </div>
        </form>
      )}
      {dirty && <p className="muted">Hay cambios sin guardar.</p>}
    </SectionCard>
  );
}
