import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useProjectStore } from "../stores/projectStore";

interface TypeEntry {
  ordinal: number;
  name: string;
  kind: string;
  type: string;
}

const KIND_COLORS: Record<string, string> = {
  struct: "var(--accent)",
  union: "var(--orange)",
  enum: "var(--green)",
  typedef: "var(--yellow)",
  funcptr: "var(--red)",
};

export function LocalTypes() {
  const { activeProjectId } = useProjectStore();
  const [types, setTypes] = useState<TypeEntry[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const parentRef = useRef<HTMLDivElement>(null);

  const fetchData = useCallback((initial = false) => {
    if (!activeProjectId) return;
    if (initial) setLoading(true);
    fetch(`/api/projects/${activeProjectId}/local_types`)
      .then((r) => r.json())
      .then((res) => setTypes(res.items || []))
      .catch(() => { if (initial) setTypes([]); })
      .finally(() => setLoading(false));
  }, [activeProjectId]);

  useEffect(() => {
    if (!activeProjectId) { setTypes([]); return; }
    fetchData(true);
  }, [activeProjectId, fetchData]);

  const filtered = useMemo(() => {
    if (!filter) return types;
    const lower = filter.toLowerCase();
    return types.filter((e) =>
      e.name.toLowerCase().includes(lower) ||
      e.kind.toLowerCase().includes(lower) ||
      e.type.toLowerCase().includes(lower),
    );
  }, [types, filter]);

  const virtualizer = useVirtualizer({
    count: filtered.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 24,
    overscan: 20,
  });

  return (
    <div className="panel" onFocus={() => fetchData()} tabIndex={-1}>
      <div className="panel-header">
        <span>Local Types ({filtered.length})</span>
      </div>
      <div className="func-filter-bar">
        <input className="func-filter-input" type="text" placeholder="Filter..."
          value={filter} onChange={(e) => setFilter(e.target.value)} />
      </div>
      <div className="panel-body func-list-body" ref={parentRef}>
        {loading && <div className="empty-hint">Loading...</div>}
        {!loading && types.length === 0 && <div className="empty-hint">No local types</div>}
        {!loading && filtered.length > 0 && (
          <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
            {virtualizer.getVirtualItems().map((vRow) => {
              const entry = filtered[vRow.index];
              return (
                <div key={vRow.key} className="func-row"
                  style={{ position: "absolute", top: 0, left: 0, width: "100%", height: vRow.size, transform: `translateY(${vRow.start}px)` }}
                >
                  <span className="type-kind" style={{ color: KIND_COLORS[entry.kind] || "var(--text-muted)" }}>{entry.kind}</span>
                  <span className="func-name">{entry.name}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
