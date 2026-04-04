import { useCallback, useRef, useEffect } from "react";
import { useViewStore } from "../stores/viewStore";
import { useProjectStore } from "../stores/projectStore";
import { highlightOps } from "../utils/highlightAsm";
import { ChannelBadge } from "../components/ChannelBadge";

export function Disassembly({ tabId = "disassembly" }: { tabId?: string }) {
  const store = useViewStore();
  const ch = store.getTabChannel(tabId);
  const channel = store.getChannel(ch);
  const { activeProjectId } = useProjectStore();
  const containerRef = useRef<HTMLDivElement>(null);

  const { currentFunc, funcData, loading, error,
    highlightDisasmAddrs, highlightToken } = channel;

  const activate = useCallback(() => store.setActiveChannel(ch), [store, ch]);

  useEffect(() => {
    if (highlightDisasmAddrs.length === 0 || !containerRef.current) return;
    const firstAddr = highlightDisasmAddrs[0];
    const el = containerRef.current.querySelector(`[data-addr="${firstAddr}"]`);
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [highlightDisasmAddrs]);

  const handleClick = useCallback(
    (addr: string, e: React.MouseEvent) => {
      activate();

      if (e.detail === 2 && activeProjectId) {
        const insn = funcData?.disasm.find((d) => d.addr === addr);
        if (insn) {
          const match = insn.operands.match(
            /\b(sub_[0-9A-Fa-f]+|loc_[0-9A-Fa-f]+|0x[0-9A-Fa-f]+|_[A-Za-z_]\w*)\b/,
          );
          if (match) {
            store.navigateTo(ch, activeProjectId, match[1]);
            return;
          }
        }
      }

      const target = (e.target as HTMLElement).getAttribute?.("data-token");
      if (target) {
        store.setHighlightToken(ch, target === highlightToken ? null : target);
        return;
      }

      store.highlightFromDisasm(ch, addr);
    },
    [store, ch, funcData, activeProjectId, highlightToken, activate],
  );

  return (
    <div className="panel disasm-panel" onMouseDown={activate}>
      <div className="panel-header">
        <ChannelBadge tabId={tabId} />
        <span>Disassembly{currentFunc ? `: ${currentFunc}` : ""}</span>
      </div>
      <div className="panel-body code-panel-body" ref={containerRef}>
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
