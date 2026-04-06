import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useProjectStore } from "../stores/projectStore";
import { useViewStore } from "../stores/viewStore";
import { listNames } from "../api/client";
import { useCodeContextMenu } from "../hooks/useCodeContextMenu";

interface NameEntry {
  addr: string;
  name: string;
}

export function NamesList() {
  const { activeProjectId } = useProjectStore();
  const navigateActive = useViewStore((s) => s.navigateActive);
  const [names, setNames] = useState<NameEntry[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const parentRef = useRef<HTMLDivElement>(null);

  const fetchData = useCallback((initial = false) => {
    if (!activeProjectId) return;
    if (initial) setLoading(true);
    listNames(activeProjectId)
      .then((res: any) => setNames(res.items || []))
      .catch(() => { if (initial) setNames([]); })
      .finally(() => setLoading(false));
  }, [activeProjectId]);

  useEffect(() => {
    if (!activeProjectId) { setNames([]); return; }
    fetchData(true);
  }, [activeProjectId, fetchData]);

  const filtered = useMemo(() => {
    if (!filter) return names;
    const lower = filter.toLowerCase();
    return names.filter((e) =>
      e.name.toLowerCase().includes(lower) || e.addr.toLowerCase().includes(lower),
    );
  }, [names, filter]);

  const virtualizer = useVirtualizer({
    count: filtered.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 24,
    overscan: 20,
  });

  const onContextMenu = useCodeContextMenu();

  const handleClick = useCallback(
    (entry: NameEntry) => {
      if (activeProjectId) navigateActive(activeProjectId, entry.addr);
    },
    [activeProjectId, navigateActive],
  );

  return (
    <div className="panel" onFocus={() => fetchData()} tabIndex={-1}>
      <div className="panel-header">
        <span>Names ({filtered.length})</span>
      </div>
      <div className="func-filter-bar">
        <input className="func-filter-input" type="text" placeholder="Filter..."
          value={filter} onChange={(e) => setFilter(e.target.value)} />
      </div>
      <div className="panel-body func-list-body" ref={parentRef}>
        {loading && <div className="empty-hint">Loading...</div>}
        {!loading && names.length === 0 && <div className="empty-hint">No names</div>}
        {!loading && filtered.length > 0 && (
          <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
            {virtualizer.getVirtualItems().map((vRow) => {
              const entry = filtered[vRow.index];
              return (
                <div key={vRow.key} className="func-row"
                  style={{ position: "absolute", top: 0, left: 0, width: "100%", height: vRow.size, transform: `translateY(${vRow.start}px)` }}
                  onClick={() => handleClick(entry)}
                  onContextMenu={onContextMenu}
                  data-addr={entry.addr}
                  data-token={entry.name}
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
