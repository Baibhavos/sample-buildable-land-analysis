// Thin client for the buildable-land analysis backend.

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://127.0.0.1:8000";

// Use the standard GeoJSON types (from @types/geojson, pulled in by maplibre-gl)
// so geometries are directly assignable to MapLibre sources.
export type Geometry = GeoJSON.Geometry;
export type FeatureCollection = GeoJSON.FeatureCollection;

export type ConstraintConfig = {
  enabled: boolean;
  setback_ft: number;
  label: string;
};

export type AppConfig = {
  working_crs: string;
  boundary_setback_ft: number;
  constraints: Record<string, ConstraintConfig>;
};

export type BreakdownItem = {
  category: string;
  label: string;
  acres: number;
  pct_of_parcel: number;
};

export type AnalyzeResponse = {
  parcel_id: string | null;
  parcel_acres: number;
  buildable_acres: number;
  buildable_acres_rounded: number;
  breakdown: BreakdownItem[];
  buildable_geojson: FeatureCollection;
  excluded_geojson: FeatureCollection;
  config_used: AppConfig;
  warnings: string[];
};

export type Overrides = {
  boundary_setback_ft?: number;
  working_crs?: string;
  constraints?: Record<string, { enabled?: boolean; setback_ft?: number }>;
};

export type AnalyzeRequest = {
  parcel_id: string;
  carve_outs?: Geometry[];
  restores?: Geometry[];
  overrides?: Overrides;
};

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export function getConfig() {
  return req<AppConfig>("/api/config");
}

export function getParcels() {
  return req<{ count: number; parcels: unknown[]; geojson: FeatureCollection }>("/api/parcels");
}

export function analyze(body: AnalyzeRequest) {
  return req<AnalyzeResponse>("/api/analyze", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// Shared color palette (kept in sync with the map layer paint + legend).
export const CATEGORY_COLORS: Record<string, string> = {
  buildable: "#22c55e",
  wetlands: "#14b8a6",
  floodplain: "#3b82f6",
  transmission_lines: "#f59e0b",
  buildings: "#6b7280",
  boundary_setback: "#a855f7",
  manual_carveout: "#ef4444",
  other: "#ec4899",
};
