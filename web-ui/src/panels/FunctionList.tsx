import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { listFuncs } from "../api/client";
import { useProjectStore } from "../stores/projectStore";
import { useViewStore } from "../stores/viewStore";

// FunctionList navigates on the active channel
interface FuncEntry {
  addr: string;
  name: string;
  size?: number;
}

export function FunctionList() {
  const { activeProjectId } = useProjectStore();
  const { navigateActive, activeChannel, getChannel } = useViewStore();
  const currentFunc = getChannel(activeChannel).currentFunc;
  const [functions, setFunctions] = useState<FuncEntry[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const parentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!activeProjectId) {
      setFunctions([]);
      return;
    }
    setLoading(true);
    listFuncs(activeProjectId)
      .then((res) => {
        const funcs = ((res as Record<string, unknown>).items ?? (res as Record<string, unknown>).functions) as FuncEntry[] || [];
        setFunctions(funcs);
      })
      .catch(() => setFunctions([]))
      .finally(() => setLoading(false));
  }, [activeProjectId]);

  const filtered = useMemo(() => {
    if (!filter) return functions;
    const lower = filter.toLowerCase();
    return functions.filter(
      (f) =>
        f.name.toLowerCase().includes(lower) ||
        f.addr.toLowerCase().includes(lower),
    );
  }, [functions, filter]);

  const virtualizer = useVirtualizer({
    count: filtered.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 24,
    overscan: 20,
  });

  const handleClick = useCallback(
    (func: FuncEntry) => {
      if (activeProjectId) {
        navigateActive(activeProjectId, func.addr);
      }
    },
    [activeProjectId, navigateActive],
  );

  return (
    <div className="panel func-panel">
      <div className="panel-header">
        <span>Functions ({filtered.length})</span>
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
        {!loading && functions.length === 0 && (
          <div className="empty-hint">No functions</div>
        )}
        {!loading && filtered.length > 0 && (
          <div
            style={{
              height: virtualizer.getTotalSize(),
              position: "relative",
            }}
          >
            {virtualizer.getVirtualItems().map((vRow) => {
              const func = filtered[vRow.index];
              const isActive = func.addr === currentFunc;
              const isNamed = !func.name.startsWith("sub_");
              return (
                <div
                  key={vRow.key}
                  className={`func-row ${isActive ? "active" : ""} ${isNamed ? "" : "unnamed"}`}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    height: vRow.size,
                    transform: `translateY(${vRow.start}px)`,
                  }}
                  onClick={() => handleClick(func)}
                >
                  <span className="func-addr">{func.addr}</span>
                  <span className="func-name">{func.name}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
