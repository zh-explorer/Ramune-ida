import { useCallback, useRef, useEffect } from "react";
import { useViewStore } from "../stores/viewStore";
import { useProjectStore } from "../stores/projectStore";
import { findNavTarget } from "../utils/codeNav";
import { highlightC } from "../utils/highlight";
import { ChannelBadge } from "../components/ChannelBadge";

export function Decompile({ tabId = "decompile" }: { tabId?: string }) {
  const store = useViewStore();
  const ch = store.getTabChannel(tabId);
  const channel = store.getChannel(ch);
  const { activeProjectId } = useProjectStore();
  const containerRef = useRef<HTMLDivElement>(null);

  const { currentFunc, funcName, funcData, loading, error,
    highlightDecompileLines, highlightToken } = channel;

  // Set this channel as active when interacted with
  const activate = useCallback(() => store.setActiveChannel(ch), [store, ch]);

  useEffect(() => {
    if (highlightDecompileLines.length === 0 || !containerRef.current) return;
    const firstLine = highlightDecompileLines[0];
    const el = containerRef.current.querySelector(`[data-line="${firstLine}"]`);
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [highlightDecompileLines]);

  const handleClick = useCallback(
    (lineIdx: number, e: React.MouseEvent) => {
      activate();

      if (e.ctrlKey || e.metaKey) {
        const line = funcData?.decompile[lineIdx];
        if (line && activeProjectId) {
          const target = findNavTarget(line.text, 0);
          if (target) {
            store.navigateTo(ch, activeProjectId, target);
            return;
          }
        }
      }

      if (e.detail === 2) {
        // Double-click on token → navigate
        const target = (e.target as HTMLElement).getAttribute?.("data-token");
        if (target && activeProjectId) {
          store.navigateTo(ch, activeProjectId, target);
          return;
        }
      }

      const target = (e.target as HTMLElement).getAttribute?.("data-token");
      if (target) {
        store.setHighlightToken(ch, target === highlightToken ? null : target);
        return;
      }

      store.highlightFromDecompile(ch, lineIdx);
    },
    [store, ch, funcData, activeProjectId, highlightToken, activate],
  );

  const title = funcName || currentFunc || "";

  return (
    <div className="panel decompile-panel" onMouseDown={activate}>
      <div className="panel-header">
        <ChannelBadge tabId={tabId} />
        <span>Decompile{title ? `: ${title}` : ""}</span>
      </div>
      <div className="panel-body code-panel-body" ref={containerRef}>
        {loading && <div className="code-overlay">Loading...</div>}
        {error && <div className="code-overlay error-msg">{error}</div>}
        {!currentFunc && !loading && (
          <div className="empty-hint">
            Select a function from the list
            <br />
            <span className="empty-hint-sub">Click token to highlight, double-click to navigate</span>
          </div>
        )}
        {funcData && (
          <div className="code-lines">
            {funcData.decompile.map((line) => {
              const lineHl = highlightDecompileLines.includes(line.line);
              return (
                <div
                  key={line.line}
                  data-line={line.line}
                  className={`code-line ${lineHl ? "code-line-hl" : ""}`}
                  onClick={(e) => handleClick(line.line, e)}
                >
                  <span className="code-lineno">{line.line + 1}</span>
                  <span className="code-text">{highlightC(line.text, highlightToken)}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
