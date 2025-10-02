import { useMemo, useState } from "react";
import { ApiClient, ApiError } from "../api";
import { SectionCard } from "../components/SectionCard";
import { SyncTimeResponse, TimeStatus } from "../types";

interface SystemTimePanelProps {
  api: ApiClient | null;
  status: TimeStatus | null;
  loading: boolean;
  onRefresh: () => Promise<unknown> | unknown;
  onSynced: () => Promise<unknown> | unknown;
  onError: (message: string) => void;
}

function formatBoolean(value: boolean | null | undefined) {
  if (value === true) return "Sí";
  if (value === false) return "No";
  return "Desconocido";
}

function formatDate(value: string | null | undefined, timeZone?: string | null) {
  if (!value) {
    return "—";
  }
  try {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    const options: Intl.DateTimeFormatOptions = {
      dateStyle: "medium",
      timeStyle: "medium",
    };
    if (timeZone) {
      options.timeZone = timeZone;
    }
    const formatter = new Intl.DateTimeFormat(undefined, options);
    return formatter.format(date);
  } catch (error) {
    return value;
  }
}

export function SystemTimePanel({ api, status, loading, onRefresh, onSynced, onError }: SystemTimePanelProps) {
  const [syncing, setSyncing] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);

  const disabled = useMemo(() => loading || syncing || !api, [api, loading, syncing]);

  const handleSync = async () => {
    if (!api || syncing) {
      return;
    }
    setSyncing(true);
    setSuccessMessage(null);
    setWarnings([]);
    try {
      const response: SyncTimeResponse = await api.syncTime();
      setSuccessMessage(response.message ?? "Sincronización solicitada.");
      setWarnings(response.warnings ?? []);
      await onSynced();
    } catch (error) {
      if (error instanceof ApiError) {
        onError(error.message);
      } else {
        onError("No se pudo sincronizar la hora con el servidor NTP.");
      }
    } finally {
      setSyncing(false);
    }
  };

  const handleRefresh = async () => {
    setSuccessMessage(null);
    setWarnings([]);
    await onRefresh();
  };

  return (
    <SectionCard
      id="system-time"
      title="Hora del sistema"
      description="Verifica la sincronización antes de iniciar una nueva sesión de adquisición."
      actions={
        <div className="actions">
          <button type="button" className="secondary" onClick={handleRefresh} disabled={loading || syncing}>
            Actualizar
          </button>
          <button type="button" onClick={handleSync} disabled={disabled}>
            {syncing ? "Sincronizando…" : "Sincronizar con NTP"}
          </button>
        </div>
      }
    >
      {status ? (
        <div className="time-grid">
          <div className="time-primary">
            <p className="time-reading">{formatDate(status.system_time, status.timezone)}</p>
            {status.timezone && <p className="muted">Zona horaria: {status.timezone}</p>}
            {successMessage && <p className="success-text">{successMessage}</p>}
            {warnings.map((warning) => (
              <p key={warning} className="warning-text">
                {warning}
              </p>
            ))}
          </div>
          <dl className="time-meta">
            <div>
              <dt>NTP habilitado</dt>
              <dd>{formatBoolean(status.ntp_enabled)}</dd>
            </div>
            <div>
              <dt>Sincronizado</dt>
              <dd>{formatBoolean(status.ntp_synchronized)}</dd>
            </div>
            <div>
              <dt>Última sincronización exitosa</dt>
              <dd>{formatDate(status.last_successful_sync, status.timezone)}</dd>
            </div>
            <div>
              <dt>Último intento</dt>
              <dd>{formatDate(status.last_attempt_sync, status.timezone)}</dd>
            </div>
            <div>
              <dt>Servidor NTP</dt>
              <dd>
                {status.server_name || status.server_address ? (
                  <span>
                    {status.server_name}
                    {status.server_name && status.server_address ? " · " : ""}
                    {status.server_address}
                  </span>
                ) : (
                  "—"
                )}
              </dd>
            </div>
          </dl>
        </div>
      ) : (
        <p className="muted">{loading ? "Cargando estado horario…" : "No se pudo obtener el estado horario."}</p>
      )}
    </SectionCard>
  );
}
