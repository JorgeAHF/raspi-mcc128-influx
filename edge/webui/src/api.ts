import {
  PreviewMessagePayload,
  PreviewStreamOptions,
  SessionStatusResponse,
  StartSessionRequest,
  StationConfig,
  LogsResponse,
  StorageSettings,
  StopResponse,
  SyncTimeResponse,
  TimeStatus,
} from "./types";

export interface ApiClientOptions {
  baseUrl?: string;
  getToken?: () => string | null | undefined;
}

export class ApiError extends Error {
  public readonly status: number;
  public readonly details: unknown;

  constructor(message: string, status: number, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

const defaultBaseUrl = import.meta.env.VITE_API_BASE_URL || "";

export class ApiClient {
  private readonly baseUrl: string;
  private readonly getToken: () => string | null | undefined;

  constructor(options?: ApiClientOptions) {
    this.baseUrl = options?.baseUrl?.replace(/\/$/, "") || defaultBaseUrl;
    this.getToken = options?.getToken || (() => null);
  }

  private resolveUrl(path: string): string {
    if (!path.startsWith("/")) {
      path = `/${path}`;
    }
    if (!this.baseUrl) {
      return path;
    }
    return `${this.baseUrl}${path}`;
  }

  private buildHeaders(additional?: HeadersInit, options?: { json?: boolean }): Headers {
    const headers = new Headers(additional);
    const includeJson = options?.json ?? true;
    if (includeJson && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const token = this.getToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
    return headers;
  }

  private async handleResponse<T>(response: Response): Promise<T> {
    if (response.ok) {
      if (response.status === 204) {
        return undefined as T;
      }
      const contentType = response.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {
        return (await response.json()) as T;
      }
      return (await response.text()) as unknown as T;
    }

    let details: unknown;
    try {
      const contentType = response.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {
        details = await response.json();
      } else {
        details = await response.text();
      }
    } catch (error) {
      details = undefined;
    }

    const message =
      typeof details === "object" && details !== null && "detail" in details
        ? String((details as { detail: unknown }).detail)
        : `Error ${response.status}`;
    throw new ApiError(message, response.status, details);
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(this.resolveUrl(path), {
      ...init,
      headers: this.buildHeaders(init?.headers, {
        json: init?.body !== undefined && init.body !== null,
      }),
    });
    return this.handleResponse<T>(response);
  }

  async getStationConfig(): Promise<StationConfig> {
    return this.request<StationConfig>("/config/mcc128");
  }

  async updateStationConfig(payload: StationConfig): Promise<StationConfig> {
    return this.request<StationConfig>("/config/mcc128", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  }

  async getStorageSettings(): Promise<StorageSettings> {
    return this.request<StorageSettings>("/config/storage");
  }

  async updateStorageSettings(payload: StorageSettings): Promise<StorageSettings> {
    return this.request<StorageSettings>("/config/storage", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  }

  async getSessionStatus(): Promise<SessionStatusResponse> {
    return this.request<SessionStatusResponse>("/acquisition/session");
  }

  async getTimeStatus(): Promise<TimeStatus> {
    return this.request<TimeStatus>("/system/time");
  }

  async getLogs(limit = 50): Promise<LogsResponse> {
    const params = new URLSearchParams();
    if (limit) {
      params.set("limit", String(limit));
    }
    const query = params.toString();
    const path = `/logs${query ? `?${query}` : ""}`;
    return this.request<LogsResponse>(path);
  }

  async startAcquisition(payload: StartSessionRequest): Promise<SessionStatusResponse["session"]> {
    return this.request("/acquisition/start", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  async stopAcquisition(): Promise<StopResponse> {
    return this.request<StopResponse>("/acquisition/stop", {
      method: "POST",
    });
  }

  async syncTime(): Promise<SyncTimeResponse> {
    return this.request<SyncTimeResponse>("/system/time/sync", {
      method: "POST",
    });
  }

  openPreviewStream(
    options: PreviewStreamOptions,
    onMessage: (payload: PreviewMessagePayload) => void,
    onError?: (error: unknown) => void,
  ): () => void {
    const controller = new AbortController();
    const params = new URLSearchParams();
    if (options.channels && options.channels.length > 0) {
      for (const channel of options.channels) {
        params.append("channels", String(channel));
      }
    }
    if (options.max_duration_s) {
      params.set("max_duration_s", String(options.max_duration_s));
    }
    if (options.downsample && options.downsample > 1) {
      params.set("downsample", String(options.downsample));
    }
    const query = params.toString();
    const url = `/preview/stream${query ? `?${query}` : ""}`;

    const start = async () => {
      try {
        const response = await fetch(this.resolveUrl(url), {
          method: "GET",
          headers: this.buildHeaders({ Accept: "text/event-stream" }, { json: false }),
          signal: controller.signal,
        });
        if (!response.ok || !response.body) {
          throw new ApiError(`No se pudo abrir la vista previa (${response.status})`, response.status);
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";
        while (true) {
          const { value, done } = await reader.read();
          if (done) {
            break;
          }
          buffer += decoder.decode(value, { stream: true });
          let boundary = buffer.indexOf("\n\n");
          while (boundary !== -1) {
            const rawEvent = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            boundary = buffer.indexOf("\n\n");
            const lines = rawEvent.split(/\n+/).map((line) => line.trim());
            const dataLines = lines
              .filter((line) => line.startsWith("data:"))
              .map((line) => line.replace(/^data:\s*/, ""));
            if (dataLines.length === 0) {
              continue;
            }
            const payloadRaw = dataLines.join("\n");
            try {
              const payload = JSON.parse(payloadRaw) as PreviewMessagePayload;
              onMessage(payload);
            } catch (error) {
              console.error("No se pudo parsear el evento SSE", error);
            }
          }
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          onError?.(error);
        }
      }
    };

    start();
    return () => controller.abort();
  }
}

export const createApiClient = (options?: ApiClientOptions): ApiClient => new ApiClient(options);
