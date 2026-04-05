import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { survey } from "../api/client";
import { useProjectStore } from "../stores/projectStore";
import { useViewStore } from "../stores/viewStore";

interface ExportEntry {
  addr: string;
  name: string;
}

export function ExportsList() {
  const { activeProjectId } = useProjectStore();
  const navigateActive = useViewStore((s) => s.navigateActive);
  const [exports, setExports] = useState<ExportEntry[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const parentRef = useRef<HTMLDivElement>(null);

  const fetchData = useCallback((initial = false) => {
    if (!activeProjectId) return;
    if (initial) setLoading(true);
    survey(activeProjectId)
      .then((res: any) => setExports(res.exports || []))
      .catch(() => { if (initial) setExports([]); })
      .finally(() => setLoading(false));
  }, [activeProjectId]);

  useEffect(() => {
    if (!activeProjectId) { setExports([]); return; }
    fetchData(true);
  }, [activeProjectId, fetchData]);

  const filtered = useMemo(() => {
    if (!filter) return exports;
    const lower = filter.toLowerCase();
    return exports.filter((e) =>
      e.name.toLowerCase().includes(lower) || e.addr.toLowerCase().includes(lower),
    );
  }, [exports, filter]);

  const virtualizer = useVirtualizer({
    count: filtered.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 24,
    overscan: 20,
  });

  const handleClick = useCallback(
    (entry: ExportEntry) => {
      if (activeProjectId) navigateActive(activeProjectId, entry.addr);
    },
    [activeProjectId, navigateActive],
  );

  return (
    <div className="panel" onFocus={() => fetchData()} tabIndex={-1}>
      <div className="panel-header">
        <span>Exports ({filtered.length})</span>
      </div>
      <div className="func-filter-bar">
        <input className="func-filter-input" type="text" placeholder="Filter..."
          value={filter} onChange={(e) => setFilter(e.target.value)} />
      </div>
      <div className="panel-body func-list-body" ref={parentRef}>
        {loading && <div className="empty-hint">Loading...</div>}
        {!loading && exports.length === 0 && <div className="empty-hint">No exports</div>}
        {!loading && filtered.length > 0 && (
          <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
            {virtualizer.getVirtualItems().map((vRow) => {
              const entry = filtered[vRow.index];
              return (
                <div key={vRow.key} className="func-row"
                  style={{ position: "absolute", top: 0, left: 0, width: "100%", height: vRow.size, transform: `translateY(${vRow.start}px)` }}
                  onClick={() => handleClick(entry)}
                >
                  <span className="func-addr">{entry.addr}</span>
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
