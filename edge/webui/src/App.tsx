import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiClient, ApiError, createApiClient } from "./api";
import { ErrorBanner } from "./components/ErrorBanner";
import { TokenManager } from "./components/TokenManager";
import { PreviewDashboard } from "./pages/PreviewDashboard";
import { SystemTimePanel } from "./pages/SystemTimePanel";
import { ServiceStatusPanel } from "./pages/ServiceStatusPanel";
import { LogsPanel } from "./pages/LogsPanel";
import { StationConfigView } from "./pages/StationConfigView";
import { StorageSettingsView } from "./pages/StorageSettingsView";
import { StationConfig, StorageSettings } from "./types";

const TOKEN_KEY = "edge-webui-token";

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

export default function App() {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [stationDraft, setStationDraft] = useState<StationConfig | null>(null);
  const [storageDraft, setStorageDraft] = useState<StorageSettings | null>(null);
  const [stationDirty, setStationDirty] = useState(false);
  const [storageDirty, setStorageDirty] = useState(false);
  const [stationSaving, setStationSaving] = useState(false);
  const [storageSaving, setStorageSaving] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const queryClient = useQueryClient();
  const api: ApiClient | null = useMemo(() => {
    if (!token) {
      return null;
    }
    return createApiClient({ getToken: () => token });
  }, [token]);

  useEffect(() => {
    if (token) {
      localStorage.setItem(TOKEN_KEY, token);
    } else {
      localStorage.removeItem(TOKEN_KEY);
    }
  }, [token]);

  const stationQuery = useQuery({
    queryKey: ["station-config"],
    queryFn: () => api!.getStationConfig(),
    enabled: Boolean(api),
  });

  const storageQuery = useQuery({
    queryKey: ["storage-settings"],
    queryFn: () => api!.getStorageSettings(),
    enabled: Boolean(api),
  });

  const sessionQuery = useQuery({
    queryKey: ["session-status"],
    queryFn: () => api!.getSessionStatus(),
    enabled: Boolean(api),
    refetchInterval: 10000,
  });

  const timeQuery = useQuery({
    queryKey: ["system-time"],
    queryFn: () => api!.getTimeStatus(),
    enabled: Boolean(api),
    refetchInterval: 15000,
  });

  useEffect(() => {
    if (stationQuery.data) {
      setStationDraft(clone(stationQuery.data));
      setStationDirty(false);
    }
  }, [stationQuery.data]);

  useEffect(() => {
    if (storageQuery.data) {
      setStorageDraft(clone(storageQuery.data));
      setStorageDirty(false);
    }
  }, [storageQuery.data]);

  useEffect(() => {
    if (sessionQuery.error instanceof ApiError && sessionQuery.error.status === 401) {
      setErrorMessage("Token inválido. Actualiza las credenciales.");
    }
  }, [sessionQuery.error]);

  useEffect(() => {
    const error = stationQuery.error || storageQuery.error;
    if (error instanceof ApiError) {
      setErrorMessage(error.message);
    } else if (error) {
      setErrorMessage("Error comunicando con la API.");
    }
  }, [stationQuery.error, storageQuery.error]);

  useEffect(() => {
    if (timeQuery.error instanceof ApiError) {
      setErrorMessage(timeQuery.error.message);
    } else if (timeQuery.error) {
      setErrorMessage("No se pudo obtener la hora del sistema.");
    }
  }, [timeQuery.error]);

  const handleStationChange = (next: StationConfig) => {
    setStationDraft(next);
    setStationDirty(true);
  };

  const handleStorageChange = (next: StorageSettings) => {
    setStorageDraft(next);
    setStorageDirty(true);
  };

  const handleStationSave = async () => {
    if (!api || !stationDraft) return;
    if (!confirm("¿Sobrescribir configuración de la MCC128?")) {
      return;
    }
    setStationSaving(true);
    try {
      const updated = await api.updateStationConfig(stationDraft);
      setStationDraft(clone(updated));
      setStationDirty(false);
      await queryClient.invalidateQueries({ queryKey: ["station-config"] });
    } catch (error) {
      if (error instanceof ApiError) {
        setErrorMessage(error.message);
      } else {
        setErrorMessage("No se pudo guardar la configuración de la MCC128.");
      }
    } finally {
      setStationSaving(false);
    }
  };

  const handleStorageSave = async () => {
    if (!api || !storageDraft) return;
    if (!confirm("¿Actualizar la configuración de almacenamiento?")) {
      return;
    }
    setStorageSaving(true);
    try {
      const updated = await api.updateStorageSettings(storageDraft);
      setStorageDraft(clone(updated));
      setStorageDirty(false);
      await queryClient.invalidateQueries({ queryKey: ["storage-settings"] });
    } catch (error) {
      if (error instanceof ApiError) {
        setErrorMessage(error.message);
      } else {
        setErrorMessage("No se pudo guardar la configuración de almacenamiento.");
      }
    } finally {
      setStorageSaving(false);
    }
  };

  const handleTokenUpdate = (next: string | null) => {
    setToken(next);
    setStationDraft(null);
    setStorageDraft(null);
    setStationDirty(false);
    setStorageDirty(false);
    setErrorMessage(null);
    queryClient.clear();
  };

  const handleSessionRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ["session-status"] }).catch(() => {
      /* noop */
    });
  };

  const handleTimeRefresh = async () => {
    try {
      await timeQuery.refetch();
    } catch (error) {
      console.error("No se pudo actualizar el estado horario", error);
    }
  };

  const handleTimeSynced = async () => {
    await queryClient.invalidateQueries({ queryKey: ["system-time"] });
  };

  const previewReady = Boolean(sessionQuery.data?.active && sessionQuery.data.session?.preview);

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>MCC128 Edge UI</h1>
        <p className="muted">Gestiona la adquisición y almacenamiento desde la interfaz web.</p>
      </header>

      <TokenManager token={token} onUpdate={handleTokenUpdate} />
      <ErrorBanner message={errorMessage} onClose={() => setErrorMessage(null)} />

      {!api && <p>Introduce un token para conectar con el backend.</p>}

      <main>
        <StationConfigView
          config={stationDraft}
          onChange={handleStationChange}
          onSubmit={handleStationSave}
          onRefresh={() => stationQuery.refetch()}
          dirty={stationDirty}
          saving={stationSaving}
          loading={stationQuery.isLoading || !api}
        />

        <StorageSettingsView
          settings={storageDraft}
          onChange={handleStorageChange}
          onSubmit={handleStorageSave}
          onRefresh={() => storageQuery.refetch()}
          dirty={storageDirty}
          saving={storageSaving}
          loading={storageQuery.isLoading || !api}
        />

        <SystemTimePanel
          api={api}
          status={timeQuery.data ?? null}
          loading={timeQuery.isLoading || timeQuery.isFetching || !api}
          onRefresh={handleTimeRefresh}
          onSynced={handleTimeSynced}
          onError={(message) => setErrorMessage(message)}
        />

        <PreviewDashboard
          api={api}
          station={stationDraft}
          sessionReady={previewReady}
          onError={(message) => setErrorMessage(message)}
        />

        <ServiceStatusPanel
          api={api}
          status={sessionQuery.data ?? null}
          loading={sessionQuery.isLoading || !api}
          onRefresh={handleSessionRefresh}
          onSessionChanged={handleSessionRefresh}
          onError={(message) => setErrorMessage(message)}
        />

        <LogsPanel api={api} onError={(message) => setErrorMessage(message)} />
      </main>
    </div>
  );
}
