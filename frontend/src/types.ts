export type Pick = { champion_id: number; state: 'unknown' | 'hover' | 'locked'; role: string }
export type Draft = { allies: Pick[]; enemies: Pick[]; side: 'blue' | 'red' | 'unknown'; region: string; queue: number; patch: string }
export type Champion = { id: number; name: string; slug: string; portrait: string; tags: string[] }
export type Settings = { region: string; queue: number; patches: string[]; tiers: string[]; target_matches: number }
export type Metrics = { brier: number; log_loss: number; ece: number; matches: number; calibration: { lower: number; upper: number; count: number; predicted: number; observed: number; interval: number[] }[] }
export type Prediction = {
  ready: boolean; probability: number | null; interval: number[] | null; reason?: string; interval_label?: string;
  confidence?: string; known?: number; training_matches?: number; dataset_matches?: number; calibration_matches?: number;
  version?: string; tentative?: boolean; baseline?: number; validation_warning?: boolean;
  effects?: { champion_id: number; change: number; training_matches: number }[];
  statistics?: { kind: string; champions: number[]; matches: number; win_rate: number; interval: number[] }[];
}
export type History = { time: number; probability: number | null; confirmed: number | null; known: number; tentative: boolean; change: number | null }
export type AppState = {
  draft: Draft; mode: 'manual' | 'live' | 'replay'; prediction: Prediction; confirmed: Prediction; history: History[];
  dataset: { matches: number; training_matches: number; aging_matches: number; stored_total: number; patches: Record<string, number>; window_days: number; cutoff: number; last_refresh: number | null; oldest: number | null; newest: number | null; pending_downloads: number };
  model: null | { version: string; trained_at: number; matches: number; patches: Record<string, number>; expires_at: number; report: { groups: Record<string, { model: Metrics; baseline: Metrics }>; split: Record<string, number>; validation_warning: boolean; baseline_blue_win_rate: number } };
  settings: Settings; minimum_matches: number; api_key_configured: boolean;
  integration: { status: string; message: string; client_detected: boolean; live_enabled: boolean };
  job: { status: string; kind: string | null; message: string; result?: unknown };
  collection: null | { status: string; message?: string; updated_at: number };
  training: null | { status: string; message: string; updated_at: number; version?: string };
}
