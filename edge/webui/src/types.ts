export interface Calibration {
  gain: number;
  offset: number;
}

export interface ChannelConfig {
  index: number;
  name: string;
  unit: string;
  voltage_range: number;
  calibration: Calibration;
}

export interface DriftDetectionSettings {
  correction_threshold_ns: number | null;
}

export interface AcquisitionSettings {
  sample_rate_hz: number;
  block_size: number;
  duration_s: number | null;
  total_samples: number | null;
  drift_detection: DriftDetectionSettings;
}

export interface StationConfig {
  station_id: string;
  description?: string | null;
  acquisition: AcquisitionSettings;
  channels: ChannelConfig[];
}

export interface RetrySettings {
  max_attempts: number;
  base_delay_s: number;
  max_backoff_s: number | null;
}

export interface CSVSinkSettings {
  enabled: boolean;
  directory: string;
  rotation: "session" | "daily";
  filename_prefix: string;
  timestamp_format: string;
  delimiter: string;
  decimal: string;
  encoding: string;
  newline: string;
  write_headers: boolean;
}

export interface FTPSinkSettings {
  enabled: boolean;
  protocol: "ftp" | "sftp";
  host: string | null;
  port: number | null;
  username: string | null;
  password: string | null;
  remote_dir: string;
  local_dir: string | null;
  rotation: "session" | "periodic";
  upload_interval_s: number | null;
  passive: boolean;
}

export interface StorageSettings {
  driver: string;
  url: string;
  org: string;
  bucket: string;
  token: string;
  batch_size: number;
  timeout_s: number;
  queue_max_size: number;
  verify_ssl: boolean;
  retry: RetrySettings;
  sinks: string[];
  csv: CSVSinkSettings;
  ftp: FTPSinkSettings;
}

export interface SessionSummary {
  mode: "continuous" | "timed";
  preview: boolean;
  status: string;
  started_at: string;
  finished_at: string | null;
  station_id: string;
  error: string | null;
}

export interface SessionStatusResponse {
  active: boolean;
  session?: SessionSummary;
  last_session?: SessionSummary | null;
}

export interface StartSessionRequest {
  mode: "continuous" | "timed";
  preview: boolean;
}

export interface StopResponse {
  message: string;
  session: SessionSummary;
}

export interface PreviewChannelPayload {
  index: number;
  name: string;
  unit: string;
  values: number[];
}

export interface PreviewMessagePayload {
  station_id: string;
  captured_at_ns: number;
  timestamps_ns: number[];
  channels: PreviewChannelPayload[];
}

export interface PreviewStreamOptions {
  channels?: number[];
  max_duration_s?: number;
  downsample?: number;
}
