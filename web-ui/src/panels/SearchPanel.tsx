import { useCallback, useRef, useState } from "react";
import { searchText, searchBytes } from "../api/client";
import { useProjectStore } from "../stores/projectStore";
import { useViewStore } from "../stores/viewStore";
import { useCodeContextMenu } from "../hooks/useCodeContextMenu";

type SearchMode = "text" | "bytes";
type SearchScope = "all" | "strings" | "names" | "types" | "disasm";

interface SearchResult {
  addr?: string;
  value?: string;
  source: string;
}

const SCOPE_OPTIONS: { value: SearchScope; label: string }[] = [
  { value: "all", label: "All" },
  { value: "strings", label: "Strings" },
  { value: "names", label: "Names" },
  { value: "types", label: "Types" },
  { value: "disasm", label: "Disasm" },
];

const SOURCE_COLORS: Record<string, string> = {
  string: "var(--green)",
  name: "var(--accent)",
  type: "var(--yellow)",
  disasm: "var(--orange)",
  bytes: "var(--red)",
};

export function SearchPanel() {
  const { activeProjectId } = useProjectStore();
  const store = useViewStore();
  const onContextMenu = useCodeContextMenu();

  const [mode, setMode] = useState<SearchMode>("text");
  const [scope, setScope] = useState<SearchScope>("all");
  const [pattern, setPattern] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const doSearch = useCallback(() => {
    if (!activeProjectId || !pattern.trim()) return;
    setLoading(true);
    setError(null);

    const promise = mode === "bytes"
      ? searchBytes(activeProjectId, pattern.trim()).then((res) => ({
          total: res.total,
          matches: res.matches.map((m) => ({ addr: m.addr, source: "bytes" })),
        }))
      : searchText(activeProjectId, pattern.trim(), scope);

    promise
      .then((res) => {
        setResults(res.matches);
        setTotal(res.total);
      })
      .catch((e) => {
        setResults([]);
        setTotal(0);
        setError(e.message || "Search failed");
      })
      .finally(() => setLoading(false));
  }, [activeProjectId, pattern, mode, scope]);

  const handleClick = useCallback(
    (r: SearchResult) => {
      if (activeProjectId && r.addr) {
        const ch = store.activeChannel;
        store.navigateTo(ch, activeProjectId, r.addr);
      }
    },
    [store, activeProjectId],
  );

  return (
    <div className="panel search-panel">
      <div className="panel-header">
        <span>Search</span>
      </div>
      <div className="search-controls">
        <div className="search-mode-tabs">
          <button className={`search-mode-btn ${mode === "text" ? "active" : ""}`}
            onClick={() => setMode("text")}>Regex</button>
          <button className={`search-mode-btn ${mode === "bytes" ? "active" : ""}`}
            onClick={() => setMode("bytes")}>Bytes</button>
        </div>
        <div className="search-input-row">
          <input
            ref={inputRef}
            className="search-input"
            value={pattern}
            onChange={(e) => setPattern(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && doSearch()}
            placeholder={mode === "bytes" ? "48 8B ?? 00" : "Pattern (regex)..."}
          />
          {mode === "text" && (
            <select className="search-scope-select" value={scope}
              onChange={(e) => setScope(e.target.value as SearchScope)}>
              {SCOPE_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          )}
          <button className="search-go-btn" onClick={doSearch} disabled={loading || !pattern.trim()}>
            {loading ? "..." : "Go"}
          </button>
        </div>
      </div>
      <div className="panel-body">
        {error && <div className="empty-hint" style={{ color: "var(--red)" }}>{error}</div>}
        {!error && !loading && results.length === 0 && total === 0 && (
          <div className="empty-hint">Enter a pattern and press Enter</div>
        )}
        {!error && results.length > 0 && (
          <div className="search-results">
            <div className="xrefs-count">{total} result{total !== 1 ? "s" : ""}</div>
            {results.map((r, i) => (
              <div key={i} className="xref-item"
                onClick={() => handleClick(r)}
                onContextMenu={onContextMenu}
                data-addr={r.addr}
                data-token={r.value}
                style={{ cursor: r.addr ? "pointer" : "default" }}>
                <span className="search-source" style={{ color: SOURCE_COLORS[r.source] || "var(--text-muted)" }}>
                  {r.source}
                </span>
                {r.addr && <span className="xref-addr">{r.addr}</span>}
                {r.value && <span className="xref-text">{r.value}</span>}
              </div>
            ))}
          </div>
        )}
        {loading && <div className="empty-hint">Searching...</div>}
      </div>
    </div>
  );
}
