import { useMemo, useState } from "react";
import { ApiClient, ApiError } from "../api";
import { SectionCard } from "../components/SectionCard";
import { SessionStatusResponse, StartSessionRequest } from "../types";

interface ServiceStatusPanelProps {
  api: ApiClient | null;
  status: SessionStatusResponse | null;
  loading: boolean;
  onRefresh: () => void;
  onSessionChanged: () => void;
  onError: (message: string) => void;
}

function formatDate(value: string | null | undefined) {
  if (!value) {
    return "—";
  }
  try {
    return new Date(value).toLocaleString();
  } catch (error) {
    return value;
  }
}

export function ServiceStatusPanel({ api, status, loading, onRefresh, onSessionChanged, onError }: ServiceStatusPanelProps) {
  const [mode, setMode] = useState<StartSessionRequest["mode"]>("continuous");
  const [preview, setPreview] = useState<boolean>(true);
  const [busy, setBusy] = useState(false);

  const activeSession = status?.active ? status.session : null;
  const lastSession = !status?.active ? status?.last_session ?? null : null;

  const canStart = useMemo(() => Boolean(api && !activeSession && !busy), [api, activeSession, busy]);
  const canStop = useMemo(() => Boolean(api && activeSession && !busy), [api, activeSession, busy]);

  const handleStart = async () => {
    if (!api) return;
    setBusy(true);
    try {
      await api.startAcquisition({ mode, preview });
      onSessionChanged();
    } catch (error) {
      if (error instanceof ApiError) {
        onError(error.message);
      } else {
        onError("No se pudo iniciar la sesión de adquisición.");
      }
    } finally {
      setBusy(false);
    }
  };

  const handleStop = async () => {
    if (!api) return;
    setBusy(true);
    try {
      await api.stopAcquisition();
      onSessionChanged();
    } catch (error) {
      if (error instanceof ApiError) {
        onError(error.message);
      } else {
        onError("No se pudo detener la sesión actual.");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <SectionCard
      id="status"
      title="Estado del servicio"
      description="Controla el ciclo de vida de la adquisición y supervisa el historial reciente."
      actions={
        <div className="actions">
          <button type="button" className="secondary" onClick={onRefresh} disabled={loading || busy}>
            Actualizar
          </button>
        </div>
      }
    >
      <div className="status-grid">
        <div>
          <h3>Sesión activa</h3>
          {activeSession ? (
            <dl>
              <div>
                <dt>Modo</dt>
                <dd>{activeSession.mode}</dd>
              </div>
              <div>
                <dt>Vista previa</dt>
                <dd>{activeSession.preview ? "Sí" : "No"}</dd>
              </div>
              <div>
                <dt>Estado</dt>
                <dd>{activeSession.status}</dd>
              </div>
              <div>
                <dt>Inicio</dt>
                <dd>{formatDate(activeSession.started_at)}</dd>
              </div>
              <div>
                <dt>Última actualización</dt>
                <dd>{formatDate(activeSession.finished_at)}</dd>
              </div>
              {activeSession.error && (
                <div>
                  <dt>Error</dt>
                  <dd className="error-text">{activeSession.error}</dd>
                </div>
              )}
            </dl>
          ) : (
            <p className="muted">No hay sesiones en ejecución.</p>
          )}
        </div>
        <div>
          <h3>Última sesión</h3>
          {lastSession ? (
            <dl>
              <div>
                <dt>Modo</dt>
                <dd>{lastSession.mode}</dd>
              </div>
              <div>
                <dt>Vista previa</dt>
                <dd>{lastSession.preview ? "Sí" : "No"}</dd>
              </div>
              <div>
                <dt>Estado</dt>
                <dd>{lastSession.status}</dd>
              </div>
              <div>
                <dt>Inicio</dt>
                <dd>{formatDate(lastSession.started_at)}</dd>
              </div>
              <div>
                <dt>Fin</dt>
                <dd>{formatDate(lastSession.finished_at)}</dd>
              </div>
              {lastSession.error && (
                <div>
                  <dt>Error</dt>
                  <dd className="error-text">{lastSession.error}</dd>
                </div>
              )}
            </dl>
          ) : (
            <p className="muted">No hay registros previos.</p>
          )}
        </div>
        <div>
          <h3>Control</h3>
          <div className="control-panel">
            <label>
              <span>Modo</span>
              <select value={mode} onChange={(event) => setMode(event.target.value as StartSessionRequest["mode"])}>
                <option value="continuous">Continuo</option>
                <option value="timed">Temporizado</option>
              </select>
            </label>
            <label className="checkbox">
              <input type="checkbox" checked={preview} onChange={(event) => setPreview(event.target.checked)} />
              <span>Habilitar vista previa</span>
            </label>
            <div className="actions">
              <button type="button" onClick={handleStart} disabled={!canStart}>
                {busy && !activeSession ? "Iniciando…" : "Iniciar"}
              </button>
              <button type="button" className="danger" onClick={handleStop} disabled={!canStop}>
                {busy && activeSession ? "Deteniendo…" : "Detener"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </SectionCard>
  );
}
