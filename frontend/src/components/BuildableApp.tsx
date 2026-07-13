"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import maplibregl, { Map as MLMap, MapMouseEvent } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  analyze,
  AnalyzeResponse,
  AppConfig,
  CATEGORY_COLORS,
  FeatureCollection,
  getConfig,
  getParcels,
  Geometry,
  Overrides,
} from "@/lib/api";

type DrawMode = "carve" | "restore" | null;

const EMPTY_FC: FeatureCollection = { type: "FeatureCollection", features: [] };

// OpenStreetMap raster base map - no API key required.
const BASE_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [{ id: "osm", type: "raster", source: "osm" }],
};

function excludedColorExpression(): maplibregl.ExpressionSpecification {
  return [
    "match",
    ["get", "category"],
    "wetlands",
    CATEGORY_COLORS.wetlands,
    "floodplain",
    CATEGORY_COLORS.floodplain,
    "transmission_lines",
    CATEGORY_COLORS.transmission_lines,
    "buildings",
    CATEGORY_COLORS.buildings,
    "boundary_setback",
    CATEGORY_COLORS.boundary_setback,
    "manual_carveout",
    CATEGORY_COLORS.manual_carveout,
    CATEGORY_COLORS.other,
  ] as maplibregl.ExpressionSpecification;
}

export default function BuildableApp() {
  const mapContainer = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MLMap | null>(null);
  const mapReady = useRef(false);
  // `ready` is state (not just the ref) so data-push effects re-run once the
  // map's style + layers are actually initialized.
  const [ready, setReady] = useState(false);

  const [config, setConfig] = useState<AppConfig | null>(null);
  const [parcels, setParcels] = useState<FeatureCollection>(EMPTY_FC);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [controls, setControls] = useState<Overrides | null>(null);

  const [carveOuts, setCarveOuts] = useState<Geometry[]>([]);
  const [restores, setRestores] = useState<Geometry[]>([]);

  const [drawMode, setDrawMode] = useState<DrawMode>(null);
  const [draft, setDraft] = useState<[number, number][]>([]);

  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Refs mirror state so the (once-bound) map handlers read current values.
  const drawModeRef = useRef<DrawMode>(null);
  const draftRef = useRef<[number, number][]>([]);
  const selectedIdRef = useRef<string | null>(null);
  drawModeRef.current = drawMode;
  draftRef.current = draft;
  selectedIdRef.current = selectedId;

  // --- load config + parcels ------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [cfg, pc] = await Promise.all([getConfig(), getParcels()]);
        if (cancelled) return;
        setConfig(cfg);
        setParcels(pc.geojson);
        setControls({
          boundary_setback_ft: cfg.boundary_setback_ft,
          constraints: Object.fromEntries(
            Object.entries(cfg.constraints).map(([k, v]) => [
              k,
              { enabled: v.enabled, setback_ft: v.setback_ft },
            ]),
          ),
        });
      } catch (e) {
        if (!cancelled) setError(`Cannot reach backend at API base. ${(e as Error).message}`);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // --- init map -------------------------------------------------------------
  const setData = useCallback((id: string, data: FeatureCollection | Geometry) => {
    const map = mapRef.current;
    if (!map) return;
    const src = map.getSource(id) as maplibregl.GeoJSONSource | undefined;
    if (src) src.setData(data as GeoJSON.GeoJSON);
  }, []);

  const finishDraft = useCallback(() => {
    const pts = draftRef.current;
    if (pts.length >= 3) {
      const ring = [...pts, pts[0]];
      const poly: Geometry = { type: "Polygon", coordinates: [ring] };
      if (drawModeRef.current === "carve") setCarveOuts((p) => [...p, poly]);
      else if (drawModeRef.current === "restore") setRestores((p) => [...p, poly]);
    }
    setDraft([]);
    setDrawMode(null);
  }, []);

  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: mapContainer.current,
      style: BASE_STYLE,
      center: [-97.3, 30.11],
      zoom: 13,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({}), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "imperial" }), "bottom-left");

    map.on("load", () => {
      map.addSource("parcels", { type: "geojson", data: EMPTY_FC });
      map.addSource("excluded", { type: "geojson", data: EMPTY_FC });
      map.addSource("buildable", { type: "geojson", data: EMPTY_FC });
      map.addSource("restores", { type: "geojson", data: EMPTY_FC });
      map.addSource("draft", { type: "geojson", data: EMPTY_FC });
      map.addSource("draft-pts", { type: "geojson", data: EMPTY_FC });

      map.addLayer({
        id: "parcels-fill",
        type: "fill",
        source: "parcels",
        paint: { "fill-color": "#94a3b8", "fill-opacity": 0.12 },
      });
      map.addLayer({
        id: "parcels-line",
        type: "line",
        source: "parcels",
        paint: { "line-color": "#334155", "line-width": 1.2 },
      });
      map.addLayer({
        id: "parcels-selected",
        type: "line",
        source: "parcels",
        paint: { "line-color": "#0f172a", "line-width": 3 },
        filter: ["==", ["get", "parcel_id"], "___none___"],
      });
      map.addLayer({
        id: "excluded-fill",
        type: "fill",
        source: "excluded",
        paint: { "fill-color": excludedColorExpression(), "fill-opacity": 0.55 },
      });
      map.addLayer({
        id: "buildable-fill",
        type: "fill",
        source: "buildable",
        paint: { "fill-color": CATEGORY_COLORS.buildable, "fill-opacity": 0.5 },
      });
      map.addLayer({
        id: "buildable-line",
        type: "line",
        source: "buildable",
        paint: { "line-color": "#15803d", "line-width": 1 },
      });
      map.addLayer({
        id: "restores-line",
        type: "line",
        source: "restores",
        paint: { "line-color": "#16a34a", "line-width": 2, "line-dasharray": [2, 1] },
      });
      map.addLayer({
        id: "draft-fill",
        type: "fill",
        source: "draft",
        paint: { "fill-color": "#eab308", "fill-opacity": 0.25 },
      });
      map.addLayer({
        id: "draft-line",
        type: "line",
        source: "draft",
        paint: { "line-color": "#a16207", "line-width": 2 },
      });
      map.addLayer({
        id: "draft-pts",
        type: "circle",
        source: "draft-pts",
        paint: { "circle-radius": 4, "circle-color": "#a16207" },
      });

      mapReady.current = true;
      // Flip readiness state so the data-push effects run and render the
      // current parcels/results (the effects hold live state, this closure
      // would only see the initial values).
      setReady(true);
    });

    const hasParcelLayer = () => !!map.getLayer("parcels-fill");

    map.on("click", (e: MapMouseEvent) => {
      if (drawModeRef.current) {
        setDraft((prev) => [...prev, [e.lngLat.lng, e.lngLat.lat]]);
        return;
      }
      if (!hasParcelLayer()) return;
      const feats = map.queryRenderedFeatures(e.point, { layers: ["parcels-fill"] });
      if (feats.length) {
        const pid = feats[0].properties?.parcel_id as string;
        if (pid) setSelectedId(pid);
      }
    });

    map.on("dblclick", (e: MapMouseEvent) => {
      if (drawModeRef.current) {
        e.preventDefault();
        finishDraft();
      }
    });

    map.on("mousemove", (e: MapMouseEvent) => {
      if (!hasParcelLayer()) return;
      const hovering =
        !drawModeRef.current &&
        map.queryRenderedFeatures(e.point, { layers: ["parcels-fill"] }).length > 0;
      map.getCanvas().style.cursor = drawModeRef.current ? "crosshair" : hovering ? "pointer" : "";
    });

    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") {
        setDraft([]);
        setDrawMode(null);
      } else if (ev.key === "Enter" && drawModeRef.current) {
        finishDraft();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Toggle double-click zoom while drawing.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (drawMode) map.doubleClickZoom.disable();
    else map.doubleClickZoom.enable();
  }, [drawMode]);

  // --- push data to the map -------------------------------------------------
  useEffect(() => {
    if (!ready) return;
    setData("parcels", parcels);
    // Fit to parcels once loaded.
    const map = mapRef.current;
    if (map && parcels.features.length) {
      const b = new maplibregl.LngLatBounds();
      parcels.features.forEach((f) => addBounds(b, f.geometry));
      if (!b.isEmpty()) map.fitBounds(b, { padding: 60, duration: 600 });
    }
  }, [parcels, ready, setData]);

  useEffect(() => {
    const map = mapRef.current;
    if (map && ready && map.getLayer("parcels-selected")) {
      map.setFilter("parcels-selected", ["==", ["get", "parcel_id"], selectedId ?? "___none___"]);
    }
  }, [selectedId, ready]);

  useEffect(() => {
    if (!ready) return;
    setData("buildable", result?.buildable_geojson ?? EMPTY_FC);
    setData("excluded", result?.excluded_geojson ?? EMPTY_FC);
  }, [result, ready, setData]);

  useEffect(() => {
    if (!ready) return;
    setData("restores", { type: "FeatureCollection", features: restores.map(asFeature) } as FeatureCollection);
  }, [restores, ready, setData]);

  // Draft preview (line while <3 pts, filled polygon at >=3).
  useEffect(() => {
    const line: Geometry =
      draft.length >= 3
        ? { type: "Polygon", coordinates: [[...draft, draft[0]]] }
        : { type: "LineString", coordinates: draft };
    setData("draft", draft.length ? line : EMPTY_FC);
    setData("draft-pts", {
      type: "FeatureCollection",
      features: draft.map((p) => asFeature({ type: "Point", coordinates: p })),
    } as FeatureCollection);
  }, [draft, setData]);

  // --- analyze (debounced) --------------------------------------------------
  const analyzeKey = useMemo(
    () => JSON.stringify({ selectedId, controls, carveOuts, restores }),
    [selectedId, controls, carveOuts, restores],
  );

  useEffect(() => {
    if (!selectedId || !controls) {
      setResult(null);
      return;
    }
    const t = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const r = await analyze({
          parcel_id: selectedId,
          carve_outs: carveOuts,
          restores,
          overrides: controls,
        });
        setResult(r);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setLoading(false);
      }
    }, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analyzeKey]);

  // --- control handlers -----------------------------------------------------
  const setBoundary = (v: number) =>
    setControls((c) => (c ? { ...c, boundary_setback_ft: v } : c));

  const setConstraint = (name: string, patch: { enabled?: boolean; setback_ft?: number }) =>
    setControls((c) =>
      c
        ? {
            ...c,
            constraints: {
              ...c.constraints,
              [name]: { ...(c.constraints?.[name] || {}), ...patch },
            },
          }
        : c,
    );

  const clearEdits = () => {
    setCarveOuts([]);
    setRestores([]);
    setDraft([]);
    setDrawMode(null);
  };

  return (
    <div className="flex h-screen w-full">
      <div ref={mapContainer} className="relative flex-1" />
      <Panel
        config={config}
        controls={controls}
        selectedId={selectedId}
        result={result}
        loading={loading}
        error={error}
        drawMode={drawMode}
        draftLen={draft.length}
        carveCount={carveOuts.length}
        restoreCount={restores.length}
        onBoundary={setBoundary}
        onConstraint={setConstraint}
        onDrawMode={(m) => {
          setDraft([]);
          setDrawMode(m);
        }}
        onFinish={finishDraft}
        onClearEdits={clearEdits}
      />
    </div>
  );
}

function asFeature(geometry: Geometry) {
  return { type: "Feature" as const, properties: {}, geometry };
}

function addBounds(b: maplibregl.LngLatBounds, geom: Geometry) {
  if (geom.type === "GeometryCollection") {
    geom.geometries.forEach((g) => addBounds(b, g));
    return;
  }
  const walk = (coords: unknown): void => {
    if (typeof (coords as number[])[0] === "number") {
      const [x, y] = coords as [number, number];
      b.extend([x, y]);
    } else {
      (coords as unknown[]).forEach(walk);
    }
  };
  walk(geom.coordinates);
}

// ---------------------------------------------------------------------------
// Control + results panel
// ---------------------------------------------------------------------------
function Panel(props: {
  config: AppConfig | null;
  controls: Overrides | null;
  selectedId: string | null;
  result: AnalyzeResponse | null;
  loading: boolean;
  error: string | null;
  drawMode: DrawMode;
  draftLen: number;
  carveCount: number;
  restoreCount: number;
  onBoundary: (v: number) => void;
  onConstraint: (name: string, patch: { enabled?: boolean; setback_ft?: number }) => void;
  onDrawMode: (m: DrawMode) => void;
  onFinish: () => void;
  onClearEdits: () => void;
}) {
  const {
    config,
    controls,
    selectedId,
    result,
    loading,
    error,
    drawMode,
    draftLen,
    carveCount,
    restoreCount,
  } = props;

  return (
    <aside className="flex h-full w-[380px] shrink-0 flex-col overflow-y-auto border-l border-zinc-200 bg-white text-sm text-zinc-800">
      <header className="border-b border-zinc-200 px-4 py-3">
        <h1 className="text-base font-semibold text-zinc-900">Buildable Land Analysis</h1>
        <p className="mt-0.5 text-xs text-zinc-500">
          Click a parcel to analyze. Adjust setbacks or draw edits — totals update live.
        </p>
      </header>

      {error && (
        <div className="m-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}

      {/* Results */}
      <section className="border-b border-zinc-200 px-4 py-3">
        {!selectedId ? (
          <p className="text-xs text-zinc-500">No parcel selected.</p>
        ) : (
          <>
            <div className="flex items-baseline justify-between">
              <span className="font-medium">Parcel {selectedId}</span>
              {loading && <span className="text-xs text-zinc-400">updating…</span>}
            </div>
            {result && (
              <>
                <div className="mt-2 flex items-end gap-2">
                  <span className="text-3xl font-semibold text-green-600">
                    {result.buildable_acres.toFixed(1)}
                  </span>
                  <span className="pb-1 text-xs text-zinc-500">
                    buildable acres&nbsp;·&nbsp;≈{result.buildable_acres_rounded} ac
                  </span>
                </div>
                <div className="mt-1 text-xs text-zinc-500">
                  of {result.parcel_acres.toFixed(1)} ac parcel (
                  {((100 * result.buildable_acres) / result.parcel_acres || 0).toFixed(0)}% usable)
                </div>
                <BuildableBar result={result} />
                <ul className="mt-3 space-y-1">
                  <li className="flex items-center justify-between">
                    <span className="flex items-center gap-2">
                      <Swatch color={CATEGORY_COLORS.buildable} /> Buildable
                    </span>
                    <span>{result.buildable_acres.toFixed(2)} ac</span>
                  </li>
                  {result.breakdown.map((b) => (
                    <li key={b.category} className="flex items-center justify-between">
                      <span className="flex items-center gap-2">
                        <Swatch color={CATEGORY_COLORS[b.category] || CATEGORY_COLORS.other} />
                        {b.label}
                      </span>
                      <span className="text-zinc-600">
                        {b.acres.toFixed(2)} ac
                        <span className="ml-1 text-zinc-400">({b.pct_of_parcel}%)</span>
                      </span>
                    </li>
                  ))}
                </ul>
                {result.warnings.length > 0 && (
                  <p className="mt-2 text-xs text-amber-600">{result.warnings.join("; ")}</p>
                )}
              </>
            )}
          </>
        )}
      </section>

      {/* Draw edits */}
      <section className="border-b border-zinc-200 px-4 py-3">
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
          Manual edits
        </h2>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => props.onDrawMode(drawMode === "carve" ? null : "carve")}
            className={`rounded-md border px-2.5 py-1.5 text-xs font-medium ${
              drawMode === "carve"
                ? "border-red-500 bg-red-50 text-red-700"
                : "border-zinc-300 hover:bg-zinc-50"
            }`}
          >
            ✂ Carve out
          </button>
          <button
            onClick={() => props.onDrawMode(drawMode === "restore" ? null : "restore")}
            className={`rounded-md border px-2.5 py-1.5 text-xs font-medium ${
              drawMode === "restore"
                ? "border-green-600 bg-green-50 text-green-700"
                : "border-zinc-300 hover:bg-zinc-50"
            }`}
          >
            ＋ Restore
          </button>
          <button
            onClick={props.onFinish}
            disabled={!drawMode || draftLen < 3}
            className="rounded-md border border-zinc-300 px-2.5 py-1.5 text-xs font-medium disabled:opacity-40"
          >
            Finish shape
          </button>
          <button
            onClick={props.onClearEdits}
            disabled={!carveCount && !restoreCount}
            className="rounded-md border border-zinc-300 px-2.5 py-1.5 text-xs font-medium disabled:opacity-40"
          >
            Clear edits
          </button>
        </div>
        <p className="mt-2 text-xs text-zinc-500">
          {drawMode
            ? `Drawing ${drawMode}: click to add points, double-click or Enter to finish, Esc to cancel. (${draftLen} pts)`
            : `${carveCount} carve-out(s), ${restoreCount} restore(s).`}
        </p>
      </section>

      {/* Setback controls */}
      <section className="px-4 py-3">
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
          Setbacks &amp; constraints
        </h2>
        {controls && config && (
          <div className="space-y-4">
            <SliderRow
              label="Property-line setback"
              value={controls.boundary_setback_ft ?? 0}
              onChange={props.onBoundary}
            />
            {Object.entries(config.constraints).map(([name, c]) => {
              const cur = controls.constraints?.[name] || {};
              const enabled = cur.enabled ?? c.enabled;
              return (
                <div key={name} className="rounded-md border border-zinc-200 p-2.5">
                  <label className="flex items-center justify-between">
                    <span className="flex items-center gap-2 font-medium">
                      <Swatch color={CATEGORY_COLORS[name] || CATEGORY_COLORS.other} />
                      {c.label}
                    </span>
                    <input
                      type="checkbox"
                      checked={enabled}
                      onChange={(e) => props.onConstraint(name, { enabled: e.target.checked })}
                    />
                  </label>
                  <div className={enabled ? "" : "pointer-events-none opacity-40"}>
                    <SliderRow
                      label="buffer"
                      value={cur.setback_ft ?? c.setback_ft}
                      onChange={(v) => props.onConstraint(name, { setback_ft: v })}
                    />
                  </div>
                </div>
              );
            })}
            <p className="text-xs text-zinc-400">
              Areas computed in {config.working_crs} (local metric projection), not Web Mercator.
            </p>
          </div>
        )}
      </section>
    </aside>
  );
}

function SliderRow({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <div className="flex items-center justify-between text-xs text-zinc-600">
        <span>{label}</span>
        <span className="font-mono">{value} ft</span>
      </div>
      <input
        type="range"
        min={0}
        max={300}
        step={5}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-zinc-700"
      />
    </div>
  );
}

function BuildableBar({ result }: { result: AnalyzeResponse }) {
  const total = result.parcel_acres || 1;
  const segments = [
    { category: "buildable", acres: result.buildable_acres },
    ...result.breakdown,
  ];
  return (
    <div className="mt-3 flex h-3 w-full overflow-hidden rounded-full bg-zinc-100">
      {segments.map((s, i) => (
        <div
          key={i}
          title={`${(s as { label?: string }).label || "Buildable"}: ${s.acres.toFixed(2)} ac`}
          style={{
            width: `${(100 * s.acres) / total}%`,
            backgroundColor: CATEGORY_COLORS[s.category] || CATEGORY_COLORS.other,
          }}
        />
      ))}
    </div>
  );
}

function Swatch({ color }: { color: string }) {
  return (
    <span
      className="inline-block h-3 w-3 rounded-sm"
      style={{ backgroundColor: color }}
    />
  );
}
