import { useEffect, useMemo, useRef, useState } from "react";
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Legend,
} from "chart.js";
import { Line } from "react-chartjs-2";
import { SectionCard } from "../components/SectionCard";
import { ApiClient } from "../api";
import { PreviewMessagePayload, StationConfig } from "../types";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend);

interface PreviewDashboardProps {
  api: ApiClient | null;
  station: StationConfig | null;
  sessionReady: boolean;
  onError: (message: string) => void;
}

interface DatasetState {
  label: string;
  data: number[];
  borderColor: string;
  tension: number;
}

interface ChartState {
  labels: number[];
  datasets: Record<number, DatasetState>;
}

const MAX_POINTS = 500;
const COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"];

export function PreviewDashboard({ api, station, sessionReady, onError }: PreviewDashboardProps) {
  const [selectedChannels, setSelectedChannels] = useState<number[]>([]);
  const [downsample, setDownsample] = useState(1);
  const [streaming, setStreaming] = useState(false);
  const [chartState, setChartState] = useState<ChartState>({ labels: [], datasets: {} });
  const abortRef = useRef<(() => void) | null>(null);
  const startTimeRef = useRef<number | null>(null);

  useEffect(() => {
    if (!station) {
      setSelectedChannels([]);
      return;
    }
    setSelectedChannels((prev) => {
      const available = new Set(station.channels.map((channel) => channel.index));
      const filtered = prev.filter((index) => available.has(index));
      if (filtered.length === 0) {
        return station.channels.map((channel) => channel.index);
      }
      if (filtered.length !== prev.length) {
        return filtered;
      }
      return prev;
    });
  }, [station]);

  useEffect(() => {
    return () => {
      abortRef.current?.();
    };
  }, []);

  useEffect(() => {
    if (!sessionReady && streaming) {
      stopStream();
    }
  }, [sessionReady, streaming]);

  const handleMessage = (payload: PreviewMessagePayload) => {
    if (startTimeRef.current === null) {
      startTimeRef.current = payload.timestamps_ns[0];
    }
    const origin = startTimeRef.current ?? payload.timestamps_ns[0];
    const labels = payload.timestamps_ns.map((ts) => (ts - origin) / 1e9);
    setChartState((prev) => {
      const nextLabels = [...prev.labels, ...labels];
      const datasets: Record<number, DatasetState> = { ...prev.datasets };
      payload.channels.forEach((channel) => {
        const color = COLORS[channel.index % COLORS.length];
        const previous = prev.datasets[channel.index];
        const base: DatasetState = previous
          ? { ...previous, data: [...previous.data] }
          : {
              label: `${channel.name} (${channel.unit})`,
              data: [],
              borderColor: color,
              tension: 0.1,
            };
        base.data.push(...channel.values);
        datasets[channel.index] = base;
      });
      const trimmedLabels = nextLabels.slice(-MAX_POINTS);
      const trimLength = trimmedLabels.length;
      Object.entries(datasets).forEach(([key, dataset]) => {
        dataset.data = dataset.data.slice(-trimLength);
        datasets[Number(key)] = { ...dataset };
      });
      return { labels: trimmedLabels, datasets };
    });
  };

  const handleError = (error: unknown) => {
    console.error("Error en stream de vista previa", error);
    onError(
      error instanceof Error
        ? error.message
        : "La vista previa se interrumpió. Revisa el estado del servicio.",
    );
    stopStream();
  };

  const startStream = () => {
    if (!api || !sessionReady) {
      onError("No hay sesión de vista previa disponible.");
      return;
    }
    setChartState({ labels: [], datasets: {} });
    startTimeRef.current = null;
    abortRef.current?.();
    abortRef.current = api.openPreviewStream(
      { channels: selectedChannels, downsample },
      handleMessage,
      handleError,
    );
    setStreaming(true);
  };

  const stopStream = () => {
    abortRef.current?.();
    abortRef.current = null;
    setStreaming(false);
  };

  const toggleChannel = (channelIndex: number) => {
    setSelectedChannels((prev) => {
      if (prev.includes(channelIndex)) {
        return prev.filter((ch) => ch !== channelIndex);
      }
      return [...prev, channelIndex];
    });
  };

  useEffect(() => {
    if (!streaming) {
      return;
    }
    // Reiniciar stream al cambiar los canales seleccionados.
    startStream();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedChannels, downsample]);

  const chartData = useMemo(() => {
    const datasets = Object.values(chartState.datasets).map((dataset) => ({
      label: dataset.label,
      data: dataset.data,
      fill: false,
      borderColor: dataset.borderColor,
      tension: dataset.tension,
      pointRadius: 0,
    }));
    return { labels: chartState.labels, datasets };
  }, [chartState]);

  return (
    <SectionCard
      id="preview"
      title="Vista previa en tiempo real"
      description="Monitorea muestras recientes desde la sesión de adquisición con vista previa."
      actions={
        <div className="actions">
          <button type="button" className="secondary" onClick={stopStream} disabled={!streaming}>
            Detener
          </button>
          <button type="button" onClick={startStream} disabled={!api || streaming}>
            Iniciar vista previa
          </button>
        </div>
      }
    >
      {!station ? (
        <p>Configura la estación para habilitar la vista previa.</p>
      ) : (
        <div className="preview-grid">
          <div className="preview-controls">
            <fieldset>
              <legend>Canales</legend>
              {station.channels.map((channel) => (
                <label key={channel.index} className="checkbox">
                  <input
                    type="checkbox"
                    checked={selectedChannels.includes(channel.index)}
                    onChange={() => toggleChannel(channel.index)}
                    disabled={streaming}
                  />
                  <span>
                    #{channel.index} · {channel.name}
                  </span>
                </label>
              ))}
              {station.channels.length === 0 && <p className="muted">No hay canales definidos.</p>}
            </fieldset>
            <label>
              <span>Downsample</span>
              <input
                type="number"
                min={1}
                value={downsample}
                onChange={(event) => setDownsample(Math.max(1, Number.parseInt(event.target.value, 10) || 1))}
                disabled={streaming}
              />
            </label>
            {!sessionReady && <p className="muted">Inicia una sesión con vista previa para habilitar el stream.</p>}
          </div>
          <div className="preview-chart">
            {chartState.labels.length === 0 ? (
              <p className="muted">No hay datos aún. Inicia la vista previa para poblar el gráfico.</p>
            ) : (
              <Line
                data={chartData}
                options={{
                  responsive: true,
                  maintainAspectRatio: false,
                  scales: {
                    x: {
                      title: {
                        display: true,
                        text: "Tiempo (s)",
                      },
                    },
                    y: {
                      title: {
                        display: true,
                        text: "Valor",
                      },
                    },
                  },
                  plugins: {
                    legend: {
                      display: true,
                      position: "bottom",
                    },
                  },
                }}
              />
            )}
          </div>
        </div>
      )}
    </SectionCard>
  );
}
