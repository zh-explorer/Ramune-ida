import { useCallback, useRef, useEffect, useState } from "react";
import { useViewStore } from "../stores/viewStore";
import { useProjectStore } from "../stores/projectStore";
import { initParser, isParserReady, tokenizeLine } from "../utils/cParser";
import { renderTokens, highlightCFallback } from "../utils/highlight";
import { ChannelBadge } from "../components/ChannelBadge";

export function Decompile({ tabId = "decompile" }: { tabId?: string }) {
  const store = useViewStore();
  const ch = store.getTabChannel(tabId);
  const channel = store.getChannel(ch);
  const { activeProjectId } = useProjectStore();
  const containerRef = useRef<HTMLDivElement>(null);
  const [parserReady, setParserReady] = useState(isParserReady());

  const { currentFunc, funcName, funcData, loading, error,
    highlightDecompileLines, highlightToken } = channel;

  const activate = useCallback(() => store.setActiveChannel(ch), [store, ch]);

  // Initialize tree-sitter parser
  useEffect(() => {
    if (!parserReady) {
      initParser().then(() => setParserReady(true)).catch((e) => console.warn("[tree-sitter] init failed:", e));
    }
  }, [parserReady]);

  useEffect(() => {
    if (highlightDecompileLines.length === 0 || !containerRef.current) return;
    const firstLine = highlightDecompileLines[0];
    const el = containerRef.current.querySelector(`[data-line="${firstLine}"]`);
    if (!el) return;
    // Only scroll if not already visible
    const rect = el.getBoundingClientRect();
    const cRect = containerRef.current.getBoundingClientRect();
    if (rect.top < cRect.top || rect.bottom > cRect.bottom) {
      el.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [highlightDecompileLines]);

  const handleClick = useCallback(
    (lineIdx: number, e: React.MouseEvent) => {
      activate();

      const targetEl = e.target as HTMLElement;
      const token = targetEl.getAttribute?.("data-token");

      if (e.detail === 2 && token && activeProjectId) {
        const isNav = targetEl.getAttribute("data-navigable") === "1";
        if (isNav) {
          // LABEL_* → local jump within current decompile
          if (/^LABEL_\d+$/.test(token) && funcData) {
            const targetLine = funcData.decompile.findIndex(
              (l) => l.text.trimStart().startsWith(token + ":"),
            );
            if (targetLine >= 0) {
              store.highlightFromDecompile(ch, targetLine);
              const el = containerRef.current?.querySelector(`[data-line="${targetLine}"]`);
              el?.scrollIntoView({ block: "center", behavior: "smooth" });
              return;
            }
          }
          store.navigateTo(ch, activeProjectId, token);
          return;
        }
      }

      if (token) {
        store.setHighlightToken(ch, token === highlightToken ? null : token);
      }

      // Always sync with disassembly
      store.highlightFromDecompile(ch, lineIdx);
    },
    [store, ch, funcData, activeProjectId, highlightToken, activate],
  );

  const title = funcName || currentFunc || "";

  // Render a line using tree-sitter or fallback
  const renderLine = useCallback(
    (text: string) => {
      if (parserReady) {
        const tokens = tokenizeLine(text);
        return renderTokens(tokens, highlightToken);
      }
      return highlightCFallback(text, highlightToken);
    },
    [parserReady, highlightToken],
  );

  return (
    <div className="panel decompile-panel" onMouseDown={activate}>
      <div className="panel-header">
        <ChannelBadge tabId={tabId} />
        <span>Decompile{title ? `: ${title}` : ""}</span>
        <div className="nav-btns">
          <button
            className="nav-btn"
            disabled={!store.canGoBack(ch)}
            onClick={() => activeProjectId && store.goBack(ch, activeProjectId)}
            title="Back"
          >◀</button>
          <button
            className="nav-btn"
            disabled={!store.canGoForward(ch)}
            onClick={() => activeProjectId && store.goForward(ch, activeProjectId)}
            title="Forward"
          >▶</button>
        </div>
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
                  <span className="code-text">{renderLine(line.text)}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
