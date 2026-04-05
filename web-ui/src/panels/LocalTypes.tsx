import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useProjectStore } from "../stores/projectStore";
import { highlightCFallback } from "../utils/highlight";

const KIND_COLORS: Record<string, string> = {
  struct: "var(--accent)",
  union: "var(--orange)",
  enum: "var(--green)",
  typedef: "var(--yellow)",
};

/** Parse "struct Foo // sizeof=0x10" into {kind, name}. Fallback for unknown format. */
function parseTypeItem(item: string): { kind: string; name: string } {
  const m = item.match(/^(struct|union|enum|typedef)\s+(\S+)/);
  if (m) return { kind: m[1], name: m[2] };
  return { kind: "unknown", name: item };
}

export function LocalTypes() {
  const { activeProjectId } = useProjectStore();
  const [items, setItems] = useState<string[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [definitions, setDefinitions] = useState<Record<string, string | null>>({});
  const [loadingDefs, setLoadingDefs] = useState<Set<string>>(new Set());
  const [expandedSet, setExpandedSet] = useState<Set<string>>(new Set());
  const parentRef = useRef<HTMLDivElement>(null);

  const fetchData = useCallback((initial = false) => {
    if (!activeProjectId) return;
    if (initial) setLoading(true);
    fetch(`/api/projects/${activeProjectId}/local_types`)
      .then((r) => r.json())
      .then((res) => setItems(res.items || []))
      .catch(() => { if (initial) setItems([]); })
      .finally(() => setLoading(false));
  }, [activeProjectId]);

  useEffect(() => {
    if (!activeProjectId) { setItems([]); return; }
    fetchData(true);
  }, [activeProjectId, fetchData]);

  useEffect(() => {
    setExpandedSet(new Set());
    setDefinitions({});
  }, [activeProjectId]);

  // Build set of known type names for click-to-navigate
  const typeNames = useMemo(() => {
    const s = new Set<string>();
    for (const item of items) {
      s.add(parseTypeItem(item).name);
    }
    return s;
  }, [items]);

  const filtered = useMemo(() => {
    if (!filter) return items;
    const lower = filter.toLowerCase();
    return items.filter((item) => item.toLowerCase().includes(lower));
  }, [items, filter]);

  // Index: type name → position in filtered list (for scrollTo)
  const nameToIndex = useMemo(() => {
    const m = new Map<string, number>();
    filtered.forEach((item, i) => m.set(parseTypeItem(item).name, i));
    return m;
  }, [filtered]);

  const fetchDefinition = useCallback((name: string) => {
    if (name in definitions) return;
    setLoadingDefs((ld) => new Set(ld).add(name));
    fetch(`/api/projects/${activeProjectId}/type_detail?name=${encodeURIComponent(name)}`)
      .then((r) => r.json())
      .then((res) => setDefinitions((d) => ({ ...d, [name]: res.definition || null })))
      .catch(() => setDefinitions((d) => ({ ...d, [name]: null })))
      .finally(() => setLoadingDefs((ld) => { const n = new Set(ld); n.delete(name); return n; }));
  }, [activeProjectId, definitions]);

  const handleClick = useCallback((name: string) => {
    setExpandedSet((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
        fetchDefinition(name);
      }
      return next;
    });
  }, [fetchDefinition]);

  const virtualizerRef = useRef<ReturnType<typeof useVirtualizer<HTMLDivElement>> | null>(null);

  /** Expand a type and scroll to it (used for nested type navigation). */
  const expandAndScrollTo = useCallback((name: string) => {
    setExpandedSet((prev) => {
      if (prev.has(name)) {
        // Already expanded — just scroll
        const idx = nameToIndex.get(name);
        if (idx !== undefined) {
          requestAnimationFrame(() => virtualizerRef.current?.scrollToIndex(idx, { align: "start" }));
        }
        return prev;
      }
      const next = new Set(prev);
      next.add(name);
      fetchDefinition(name);
      return next;
    });
    const idx = nameToIndex.get(name);
    if (idx !== undefined) {
      requestAnimationFrame(() => virtualizerRef.current?.scrollToIndex(idx, { align: "start" }));
    }
  }, [fetchDefinition, nameToIndex]);

  /** Handle clicks inside definition blocks — navigate to nested types. */
  const handleDefClick = useCallback((e: React.MouseEvent) => {
    const target = e.target as HTMLElement;
    const token = target.getAttribute?.("data-token");
    if (token && typeNames.has(token)) {
      e.stopPropagation();
      expandAndScrollTo(token);
    }
  }, [typeNames, expandAndScrollTo]);

  const virtualizer = useVirtualizer({
    count: filtered.length,
    getScrollElement: () => parentRef.current,
    estimateSize: useCallback((index: number) => {
      const { name } = parseTypeItem(filtered[index]);
      const def = definitions[name];
      if (expandedSet.has(name) && def) {
        const lineCount = def.split("\n").length;
        return 24 + lineCount * 20 + 12;
      }
      return 24;
    }, [filtered, expandedSet, definitions]),
    overscan: 20,
  });
  virtualizerRef.current = virtualizer;

  useEffect(() => {
    virtualizer.measure();
  }, [expandedSet, definitions, virtualizer]);

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
        {!loading && items.length === 0 && <div className="empty-hint">No local types</div>}
        {!loading && filtered.length > 0 && (
          <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
            {virtualizer.getVirtualItems().map((vRow) => {
              const item = filtered[vRow.index];
              const { kind, name } = parseTypeItem(item);
              const isExpanded = expandedSet.has(name);
              const def = definitions[name];
              const isDefLoading = loadingDefs.has(name);
              return (
                <div key={vRow.key}
                  style={{ position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${vRow.start}px)` }}
                >
                  <div className="func-row"
                    style={{ cursor: "pointer", background: isExpanded ? "var(--bg-active)" : undefined }}
                    onClick={() => handleClick(name)}
                  >
                    <span className="type-kind" style={{ color: KIND_COLORS[kind] || "var(--text-muted)" }}>{kind}</span>
                    <span className="func-name">{name}</span>
                  </div>
                  {isExpanded && (
                    <div className="type-def-block" onClick={handleDefClick}>
                      {isDefLoading && <span className="empty-hint">Loading...</span>}
                      {!isDefLoading && def && (
                        <pre className="type-def-code">
                          {def.split("\n").map((line, i) => (
                            <div key={i}>{highlightCFallback(line, null)}</div>
                          ))}
                        </pre>
                      )}
                      {!isDefLoading && !def && name in definitions && <span className="empty-hint">No definition</span>}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
