/** EdgeLab API client. All terminal views read through this file so the
 * data contract lives in one place. */
import { getAccessToken } from "@/lib/auth";

const BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) ||
  "http://localhost:8000";

function authHeaders(): Record<string, string> {
  const token = getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export type ExperimentSummary = {
  id: string;
  created_at: string;
  strategy: string;
  symbols: string[];
  timeframe: string;
  engine_version: string;
  dataset_fingerprint: string;
  tags: string[];
  selected_params: Record<string, number>;
  confidence: "insufficient" | "weak" | "moderate" | "strong" | null;
  n_warnings: number;
  metrics: Record<string, number | null>;
  val_sharpe_mean: number | null;
  mc_sharpe_lower: number | null;
  final_sharpe: number | null;
};

export type SeriesPoint = [string, number | null];

export type Fold = {
  index: number;
  train: [string, string];
  validate: [string, string];
  best_params: Record<string, number>;
  train_metrics: Record<string, number>;
  val_metrics: Record<string, number>;
  val_equity: SeriesPoint[];
  val_trades: Record<string, unknown>[];
};

export type HeatCell = {
  x: number;
  y: number;
  sharpe: number | null;
  max_drawdown: number | null;
  profit_factor: number | null;
  win_rate: number | null;
  n_trades: number | null;
};

export type Experiment = {
  id: string;
  created_at: string;
  engine_version: string;
  strategy: string;
  strategy_code_hash: string;
  description: string;
  symbols: string[];
  timeframe: string;
  objective: string;
  seed: number;
  tags: string[];
  selected_params: Record<string, number>;
  param_sets_tested: number;
  dataset: { fingerprint: string; symbols: string[]; start: string; end: string };
  windows: {
    train_size: number;
    val_size: number;
    test_size: number;
    expanding: boolean;
    work_range: [string, string];
    holdout_range: [string, string];
  };
  development: {
    note: string;
    metrics: Record<string, number>;
    equity: SeriesPoint[];
    drawdown: SeriesPoint[];
    exposure: SeriesPoint[];
    monthly_returns: { year: number; month: number; value: number | null }[];
    trades: Record<string, unknown>[];
    trade_pnls: number[];
  };
  walkforward: {
    aggregate: Record<string, number>;
    validation_consistency: number | null;
    param_history: Record<string, number>[];
    folds: Fold[];
  };
  sensitivity: {
    neighbor_consistency: number;
    plateau_fraction: number;
    robustness_score: number;
    n_combos: number;
    heatmap: {
      x: string;
      y: string;
      x_values: number[];
      y_values: number[];
      objective: string;
      cells: HeatCell[];
    } | null;
  };
  montecarlo: {
    cis: Record<string, Record<string, Record<string, number | null>>>;
    fan?: {
      n_paths: number;
      steps: number;
      quantiles: Record<string, number[]>;
      worst_path: number[];
      best_path: number[];
      sample_paths: number[][];
      prob_ruin: Record<string, number>;
    };
    histograms?: { end_equity: number[]; max_drawdown: number[] };
    delay_sweep?: Record<string, number>[];
  };
  regimes: Record<string, Record<string, Record<string, number>>>;
  warnings: { code: string; severity: string; message: string }[];
  confidence: { level: string; rationale: string[] };
  final_test: Record<string, number>;
  report_markdown: string;
};

export type DatasetRow = {
  symbol: string;
  timeframe: string;
  rows: number;
  start: string;
  end: string;
  sources: string[];
  checksum: string;
  updated_at: string;
};

export type DatasetDetail = {
  symbol: string;
  timeframe: string;
  fingerprint: string;
  sources: string[];
  adjustment: string;
  calendar: string;
  coverage: { start: string | null; end: string | null; rows: number };
  missing_sessions: string[];
  missing_intraday_bars: number;
  integrity: string;
  corporate_actions: string;
  preview_close: [string, number][];
};

export type Deployment = {
  id: string;
  experiment_id: string;
  strategy: string;
  strategy_code_hash: string;
  engine_version: string;
  dataset_fingerprint: string;
  params: Record<string, number>;
  confidence: string;
  validation_warnings: { code: string; severity: string }[];
  symbols: string[];
  timeframe: string;
  session: string;
  risk: Record<string, number | boolean>;
  created_at: string;
  status: string;
  status_history: Record<string, unknown>[];
  review_required: boolean;
  review_evidence: Record<string, unknown>[];
};

export type DeploymentRow = {
  id: string;
  experiment_id: string;
  strategy: string;
  symbols: string[];
  timeframe: string;
  confidence: string;
  status: string;
  review_required: boolean;
  created_at: string;
};

export type HealthRow = {
  metric: string;
  expected: number | null;
  band: [number | null, number | null];
  observed: number | null;
  n_observations: number;
  within_band: boolean | null;
};

export type DriftTrigger = {
  code: string;
  severity: string;
  message: string;
  evidence: Record<string, unknown>;
};

export type DriftResult = {
  deployment_id: string;
  status: "healthy" | "weakening" | "unstable" | "retire_recommended";
  triggers: DriftTrigger[];
};

export type PatternRecord = {
  id: string;
  deployment_id: string;
  strategy: string;
  symbol: string;
  side: string;
  ts: string;
  order_id: number;
  features: Record<string, unknown>;
  outcome: {
    net_pnl: number;
    gross_pnl: number;
    win: boolean;
    holding_bars: number;
    direction: string;
  } | null;
};

export type SimilarityResult = {
  query_features: Record<string, unknown>;
  features_used: string[];
  neighbors: (PatternRecord & { distance: number })[];
  outcome_distribution: {
    n: number;
    n_resolved?: number;
    win_rate?: number | null;
    mean_pnl?: number | null;
    median_pnl?: number | null;
    pnl_std?: number | null;
  };
  note: string;
};

export type NightlyResult = {
  date: string;
  tallies: { tested: number; rejected: number; needs_more_data: number; passed: number };
  tested: {
    hypothesis: { strategy: string; symbols: string[]; rationale: string };
    experiment_id: string;
    confidence: string;
    classification: string;
    headline: Record<string, number | null>;
  }[];
  skipped_novelty: number;
  errors: { hypothesis_id: string; strategy: string; symbols: string[]; error: string }[];
  deployment_alerts: Record<string, unknown>[];
};

export type MorningDashboard = {
  deployments: DeploymentRow[];
  deployment_alerts: DriftResult[];
  latest_research: NightlyResult | null;
  emergency_stop: boolean;
};

export type StrategyInfo = {
  name: string;
  description: string;
  params: {
    name: string;
    type: string;
    default: number | boolean | string;
    min: number | null;
    max: number | null;
    step: number | null;
    description: string;
  }[];
};

export type Note = {
  id: string;
  created_at: string;
  title: string;
  body: string;
  tags: string[];
};

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store", headers: authHeaders() });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

async function post<T>(path: string, body: unknown = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export type MarketBar = { t: string; o: number; h: number; l: number; c: number; v: number };

export const api = {
  base: BASE,
  strategies: () => get<StrategyInfo[]>("/api/v1/research/strategies"),
  marketBars: (symbol: string, timeframe = "1Day", limit = 120) =>
    get<MarketBar[]>(
      `/api/v1/market/bars?${new URLSearchParams({ symbol, timeframe, limit: String(limit) })}`,
    ),
  experiments: (params: Record<string, string> = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== ""),
    ).toString();
    return get<ExperimentSummary[]>(
      `/api/v1/research/experiments${qs ? `?${qs}` : ""}`,
    );
  },
  experiment: (id: string) => get<Experiment>(`/api/v1/research/experiments/${id}`),
  downloadPdf: async (id: string) => {
    const res = await fetch(`${BASE}/api/v1/research/experiments/${id}/report.pdf`, {
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error(await res.text());
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `edgelab-${id}.pdf`;
    a.click();
    URL.revokeObjectURL(url);
  },
  datasets: () => get<DatasetRow[]>("/api/v1/research/datasets"),
  dataset: (timeframe: string, symbol: string) =>
    get<DatasetDetail>(`/api/v1/research/datasets/${timeframe}/${symbol}`),
  notes: () => get<Note[]>("/api/v1/research/notes"),
  addNote: async (title: string, body: string, tags: string[]) => {
    const res = await fetch(`${BASE}/api/v1/research/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ title, body, tags }),
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json() as Promise<Note>;
  },
  deleteNote: async (id: string) => {
    const res = await fetch(`${BASE}/api/v1/research/notes/${id}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error(await res.text());
  },
  // ── ops ────────────────────────────────────────────────────────────
  deployments: () => get<DeploymentRow[]>("/api/v1/ops/deployments"),
  deployment: (id: string) => get<Deployment>(`/api/v1/ops/deployments/${id}`),
  createDeployment: (experiment_id: string, risk?: Record<string, unknown>) =>
    post<Deployment>("/api/v1/ops/deployments", { experiment_id, risk }),
  transitionDeployment: (
    id: string,
    to: string,
    reason: string,
    paper_evidence?: Record<string, unknown>,
  ) =>
    post<Deployment>(`/api/v1/ops/deployments/${id}/transition`, {
      to,
      reason,
      paper_evidence,
    }),
  runPaper: (id: string, opts: { start?: string; end?: string; checkpoint?: boolean } = {}) =>
    post<Record<string, unknown>>(`/api/v1/ops/deployments/${id}/paper/run`, opts),
  paperLogs: (id: string, limit = 200) =>
    get<Record<string, unknown>[]>(
      `/api/v1/ops/deployments/${id}/paper/logs?limit=${limit}`,
    ),
  // Real orders through Alpaca — paper or live, gated server-side by the
  // deployment's lifecycle status. The frontend never decides which
  // Alpaca environment is used; the backend picks it from dep.status.
  runAlpaca: (id: string, opts: { start?: string; end?: string } = {}) =>
    post<Record<string, unknown>>(`/api/v1/ops/deployments/${id}/alpaca/run`, opts),
  alpacaLogs: (id: string, live: boolean, limit = 200) =>
    get<Record<string, unknown>[]>(
      `/api/v1/ops/deployments/${id}/alpaca/logs?live=${live}&limit=${limit}`,
    ),
  deploymentHealth: (id: string) =>
    get<{ deployment_id: string; rows: HealthRow[] }>(
      `/api/v1/ops/deployments/${id}/health`,
    ),
  deploymentDrift: (id: string, regime?: string) =>
    get<DriftResult>(
      `/api/v1/ops/deployments/${id}/drift${regime ? `?regime=${regime}` : ""}`,
    ),
  emergencyStopStatus: () => get<{ emergency_stop: boolean }>("/api/v1/ops/emergency-stop"),
  emergencyStopOn: () => post<{ emergency_stop: boolean }>("/api/v1/ops/emergency-stop/on"),
  emergencyStopOff: () => post<{ emergency_stop: boolean }>("/api/v1/ops/emergency-stop/off"),
  patterns: (params: Record<string, string> = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== ""),
    ).toString();
    return get<PatternRecord[]>(`/api/v1/ops/patterns${qs ? `?${qs}` : ""}`);
  },
  similarPatterns: (features: Record<string, unknown>, k = 10) =>
    post<SimilarityResult>("/api/v1/ops/patterns/similar", { features, k }),
  triggerNightly: (symbols: string[], budget = 20, seed?: number) =>
    post<NightlyResult>("/api/v1/ops/research/nightly", { symbols, budget, seed }),
  researchQueue: (symbols?: string[]) =>
    get<Record<string, unknown>[]>(
      `/api/v1/ops/research/queue${symbols ? `?${symbols.map((s) => `symbols=${s}`).join("&")}` : ""}`,
    ),
  reports: () =>
    get<{ date: string; tallies: NightlyResult["tallies"] }[]>(
      "/api/v1/ops/research/reports",
    ),
  latestReport: () => get<NightlyResult>("/api/v1/ops/research/reports/latest"),
  morning: () => get<MorningDashboard>("/api/v1/ops/morning"),
};

export const fmt = {
  num: (v: number | null | undefined, digits = 2): string =>
    v === null || v === undefined || Number.isNaN(v) ? "—" : v.toFixed(digits),
  pct: (v: number | null | undefined, digits = 1): string =>
    v === null || v === undefined || Number.isNaN(v)
      ? "—"
      : `${(v * 100).toFixed(digits)}%`,
  signed: (v: number | null | undefined, digits = 2): string =>
    v === null || v === undefined || Number.isNaN(v)
      ? "—"
      : `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`,
  date: (iso: string | null | undefined): string =>
    iso ? iso.slice(0, 10) : "—",
  time: (iso: string | null | undefined): string =>
    iso ? iso.slice(0, 19).replace("T", " ") : "—",
  short: (s: string, n = 12): string => (s.length > n ? s.slice(0, n) + "…" : s),
};
