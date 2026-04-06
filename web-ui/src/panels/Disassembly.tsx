import { useCallback, useRef, useEffect } from "react";
import { useViewStore } from "../stores/viewStore";
import { useProjectStore } from "../stores/projectStore";
import { highlightOps } from "../utils/highlightAsm";
import { isNavigable } from "../utils/codeNav";
import { ChannelBadge } from "../components/ChannelBadge";
import { useCodeContextMenu } from "../hooks/useCodeContextMenu";

export function Disassembly({ tabId = "disassembly" }: { tabId?: string }) {
  const store = useViewStore();
  const ch = store.getTabChannel(tabId);
  const channel = store.getChannel(ch);
  const { activeProjectId } = useProjectStore();
  const containerRef = useRef<HTMLDivElement>(null);

  const { currentFunc, funcData, loading, error,
    highlightDisasmAddrs, highlightToken } = channel;

  const activate = useCallback(() => store.setActiveChannel(ch), [store, ch]);
  const onContextMenu = useCodeContextMenu(ch);

  useEffect(() => {
    if (highlightDisasmAddrs.length === 0 || !containerRef.current) return;
    const firstAddr = highlightDisasmAddrs[0];
    const el = containerRef.current.querySelector(`[data-addr="${firstAddr}"]`);
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const cRect = containerRef.current.getBoundingClientRect();
    if (rect.top < cRect.top || rect.bottom > cRect.bottom) {
      el.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [highlightDisasmAddrs]);

  const handleClick = useCallback(
    (addr: string, e: React.MouseEvent) => {
      activate();

      const tokenEl = e.target as HTMLElement;
      const token = tokenEl.getAttribute?.("data-token");

      // Double-click: navigate
      if (e.detail === 2 && token && activeProjectId && isNavigable(token)) {
        store.navigateTo(ch, activeProjectId, token);
        return;
      }

      // Single click on token: highlight all occurrences
      if (token) {
        store.setHighlightToken(ch, token === highlightToken ? null : token);
      }

      // Always sync with decompile
      store.highlightFromDisasm(ch, addr);
    },
    [store, ch, activeProjectId, highlightToken, activate],
  );

  return (
    <div className="panel disasm-panel" onMouseDown={activate}>
      <div className="panel-header">
        <ChannelBadge tabId={tabId} />
        <span>Disassembly{currentFunc ? `: ${currentFunc}` : ""}</span>
      </div>
      <div className="panel-body code-panel-body" ref={containerRef} onContextMenu={onContextMenu}>
        {loading && <div className="code-overlay">Loading...</div>}
        {error && <div className="code-overlay error-msg">{error}</div>}
        {!currentFunc && !loading && (
          <div className="empty-hint">
            Select a function from the list
            <br />
            <span className="empty-hint-sub">Double-click to navigate</span>
          </div>
        )}
        {funcData && (
          <div className="code-lines">
            {funcData.disasm.map((insn) => {
              const lineHl = highlightDisasmAddrs.includes(insn.addr);
              return (
                <div
                  key={insn.addr}
                  data-addr={insn.addr}
                  className={`code-line ${lineHl ? "code-line-hl" : ""}`}
                  onClick={(e) => handleClick(insn.addr, e)}
                >
                  <span className="disasm-addr">{insn.addr}</span>
                  <span
                    className={`disasm-mnem${highlightToken === insn.mnemonic ? " token-hl" : ""}`}
                    data-token={insn.mnemonic}
                  >{insn.mnemonic}</span>
                  <span className="disasm-ops">{highlightOps(insn.operands, highlightToken)}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
