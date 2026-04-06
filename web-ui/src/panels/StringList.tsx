import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { listStrings } from "../api/client";
import { useProjectStore } from "../stores/projectStore";
import { useViewStore } from "../stores/viewStore";
import { useCodeContextMenu } from "../hooks/useCodeContextMenu";

interface StringEntry {
  addr: string;
  value: string;
  length?: number;
}

export function StringList() {
  const { activeProjectId } = useProjectStore();
  const { navigateActive } = useViewStore();
  const [strings, setStrings] = useState<StringEntry[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const parentRef = useRef<HTMLDivElement>(null);

  const fetchStrings = useCallback((initial = false) => {
    if (!activeProjectId) return;
    if (initial) setLoading(true);
    listStrings(activeProjectId)
      .then((res) => {
        const strs = ((res as Record<string, unknown>).items ?? (res as Record<string, unknown>).strings) as StringEntry[] || [];
        setStrings(strs);
      })
      .catch(() => { if (initial) setStrings([]); })
      .finally(() => setLoading(false));
  }, [activeProjectId]);

  useEffect(() => {
    if (!activeProjectId) { setStrings([]); return; }
    fetchStrings(true);
  }, [activeProjectId, fetchStrings]);

  const filtered = useMemo(() => {
    if (!filter) return strings;
    const lower = filter.toLowerCase();
    return strings.filter(
      (s) =>
        s.value.toLowerCase().includes(lower) ||
        s.addr.toLowerCase().includes(lower),
    );
  }, [strings, filter]);

  const virtualizer = useVirtualizer({
    count: filtered.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 24,
    overscan: 20,
  });

  const onContextMenu = useCodeContextMenu();

  const handleClick = useCallback(
    (entry: StringEntry) => {
      if (activeProjectId) {
        navigateActive(activeProjectId, entry.addr);
      }
    },
    [activeProjectId, navigateActive],
  );

  return (
    <div className="panel string-panel" onFocus={() => fetchStrings()} tabIndex={-1}>
      <div className="panel-header">
        <span>Strings ({filtered.length})</span>
      </div>
      <div className="func-filter-bar">
        <input
          className="func-filter-input"
          type="text"
          placeholder="Filter..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>
      <div className="panel-body func-list-body" ref={parentRef}>
        {loading && <div className="empty-hint">Loading...</div>}
        {!loading && strings.length === 0 && (
          <div className="empty-hint">No strings</div>
        )}
        {!loading && filtered.length > 0 && (
          <div
            style={{
              height: virtualizer.getTotalSize(),
              position: "relative",
            }}
          >
            {virtualizer.getVirtualItems().map((vRow) => {
              const entry = filtered[vRow.index];
              return (
                <div
                  key={vRow.key}
                  className="func-row"
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    height: vRow.size,
                    transform: `translateY(${vRow.start}px)`,
                  }}
                  onClick={() => handleClick(entry)}
                  onContextMenu={onContextMenu}
                  data-addr={entry.addr}
                  data-token={entry.value}
                >
                  <span className="func-addr">{entry.addr}</span>
                  <span className="string-value">{entry.value}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
