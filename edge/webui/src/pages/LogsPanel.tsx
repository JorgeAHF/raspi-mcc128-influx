import { type ReactNode, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ApiClient, ApiError } from "../api";
import { SectionCard } from "../components/SectionCard";
import { LogCategory, LogEntry, LogsResponse } from "../types";

const CATEGORY_LABELS: Record<LogCategory, string> = {
  acquisition: "Adquisición MCC128",
  storage: "Almacenamiento InfluxDB",
};

interface LogsPanelProps {
  api: ApiClient | null;
  onError: (message: string) => void;
  limit?: number;
}

const LOG_REFRESH_MS = 20000;

function formatTimestamp(value: string): string {
  try {
    return new Date(value).toLocaleString();
  } catch (error) {
    return value;
  }
}

export function LogsPanel({ api, onError, limit = 50 }: LogsPanelProps) {
  const [activeTab, setActiveTab] = useState<LogCategory>("acquisition");

  const logsQuery = useQuery<LogsResponse, unknown>({
    queryKey: ["logs", limit],
    queryFn: () => api!.getLogs(limit),
    enabled: Boolean(api),
    refetchInterval: LOG_REFRESH_MS,
  });

  useEffect(() => {
    if (logsQuery.error instanceof ApiError) {
      onError(logsQuery.error.message);
    } else if (logsQuery.error) {
      onError("No se pudieron cargar los logs recientes.");
    }
  }, [logsQuery.error, onError]);

  const logs = useMemo<LogsResponse>(() => {
    if (!logsQuery.data) {
      return { acquisition: [], storage: [] };
    }
    return logsQuery.data;
  }, [logsQuery.data]);

  const counts = useMemo<Record<LogCategory, number>>(() => ({
    acquisition: logs.acquisition.length,
    storage: logs.storage.length,
  }), [logs.acquisition.length, logs.storage.length]);

  const activeEntries = logs[activeTab];
  const isLoading = logsQuery.isLoading || logsQuery.isFetching;

  const handleRefresh = () => {
    if (!logsQuery.refetch) return;
    logsQuery.refetch().catch(() => {
      /* noop */
    });
  };

  let panelContent: ReactNode;

  if (!api) {
    panelContent = <p className="muted">Conecta el backend para revisar los logs.</p>;
  } else if (isLoading && activeEntries.length === 0) {
    panelContent = <p>Cargando logs recientes…</p>;
  } else if (activeEntries.length === 0) {
    panelContent = <p className="muted">No se registraron advertencias ni errores recientes.</p>;
  } else {
    panelContent = (
      <ul className="log-list">
        {activeEntries.map((entry: LogEntry) => {
          const key = `${entry.timestamp}-${entry.logger}-${entry.message}`;
          const severity = entry.level.toLowerCase();
          return (
            <li key={key} className={`log-entry log-${severity}`}>
              <div className="log-meta">
                <span className="log-timestamp">{formatTimestamp(entry.timestamp)}</span>
                <span className="log-level">{entry.level}</span>
                <span className="log-logger">{entry.logger}</span>
              </div>
              <p className="log-message">{entry.message}</p>
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <SectionCard
      id="logs"
      title="Logs recientes"
      description="Consulta advertencias y errores emitidos por la adquisición y el almacenamiento."
      actions={
        <div className="actions">
          <button type="button" className="secondary" onClick={handleRefresh} disabled={isLoading || !api}>
            Actualizar
          </button>
        </div>
      }
    >
      <div className="tabs">
        <div className="tab-list" role="tablist">
          {(Object.keys(CATEGORY_LABELS) as LogCategory[]).map((category) => {
            const label = CATEGORY_LABELS[category];
            const isActive = category === activeTab;
            return (
              <button
                key={category}
                type="button"
                className={`tab-button${isActive ? " active" : ""}`}
                onClick={() => setActiveTab(category)}
                role="tab"
                aria-selected={isActive}
              >
                {label}
                {counts[category] > 0 && <span className="badge">{counts[category]}</span>}
              </button>
            );
          })}
        </div>
        <div className="tab-panel" role="tabpanel">
          {panelContent}
        </div>
      </div>
    </SectionCard>
  );
}
