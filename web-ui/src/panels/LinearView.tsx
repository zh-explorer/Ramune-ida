import { useCallback, useEffect, useRef, useState } from "react";
import { linearView } from "../api/client";
import { useProjectStore } from "../stores/projectStore";
import { useViewStore } from "../stores/viewStore";
import { highlightOps } from "../utils/highlightAsm";
import { ChannelBadge } from "../components/ChannelBadge";
import type { LinearLine } from "../api/types";

const CHUNK_SIZE = 150;
const LOAD_THRESHOLD = 200;

export function LinearView({ tabId = "idaview" }: { tabId?: string }) {
  const { activeProjectId } = useProjectStore();
  const store = useViewStore();
  const ch = store.getTabChannel(tabId);
  const channel = store.getChannel(ch);
  const { highlightToken, highlightDisasmAddrs, funcData } = channel;

  const [lines, setLines] = useState<LinearLine[]>([]);
  const [loading, setLoading] = useState(false);
  const [nextAddr, setNextAddr] = useState<string | null>(null);
  const [addrInput, setAddrInput] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const loadingRef = useRef(false);

  const activate = useCallback(() => store.setActiveChannel(ch), [store, ch]);

  const loadFrom = useCallback(
    async (addr: string, append = false) => {
      if (!activeProjectId || loadingRef.current) return;
      loadingRef.current = true;
      setLoading(true);
      try {
        const data = await linearView(activeProjectId, addr, CHUNK_SIZE);
        if (append) {
          setLines((prev) => [...prev, ...data.lines]);
        } else {
          setLines(data.lines);
        }
        setNextAddr(data.next);
      } catch { /* ignore */ }
      finally {
        setLoading(false);
        loadingRef.current = false;
      }
    },
    [activeProjectId],
  );

  useEffect(() => {
    if (!activeProjectId) { setLines([]); return; }
    loadFrom("0x0");
  }, [activeProjectId, loadFrom]);

  // Sync: scroll to highlighted addr, load if needed
  useEffect(() => {
    if (highlightDisasmAddrs.length === 0 || !containerRef.current) return;
    const addr = highlightDisasmAddrs[0];
    const el = containerRef.current.querySelector(`[data-addr="${addr}"]`);
    if (el) {
      el.scrollIntoView({ block: "center", behavior: "smooth" });
    } else {
      loadFrom(addr).then(() => {
        requestAnimationFrame(() => {
          containerRef.current
            ?.querySelector(`[data-addr="${addr}"]`)
            ?.scrollIntoView({ block: "center", behavior: "smooth" });
        });
      });
    }
  }, [highlightDisasmAddrs, loadFrom]);

  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el || !nextAddr || loadingRef.current) return;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < LOAD_THRESHOLD) {
      loadFrom(nextAddr, true);
    }
  }, [nextAddr, loadFrom]);

  const handleGo = useCallback(() => {
    if (addrInput) { loadFrom(addrInput); setAddrInput(""); }
  }, [addrInput, loadFrom]);

  const handleClick = useCallback(
    (line: LinearLine, e: React.MouseEvent) => {
      activate();
      const target = (e.target as HTMLElement).getAttribute?.("data-token");

      if (e.detail === 2) {
        if (target && activeProjectId) {
          store.navigateTo(ch, activeProjectId, target);
        }
        return;
      }

      if (target) {
        store.setHighlightToken(ch, target === highlightToken ? null : target);
      }

      if (line.type === "code" && line.addr && activeProjectId) {
        const clickedFunc = line.func_name;
        const currentFunc = funcData?.func?.name;
        if (clickedFunc && clickedFunc !== currentFunc) {
          store.navigateTo(ch, activeProjectId, line.addr);
        } else {
          store.highlightFromDisasm(ch, line.addr);
        }
      }
    },
    [store, ch, activeProjectId, highlightToken, funcData, activate],
  );

  return (
    <div className="panel linear-panel" onMouseDown={activate}>
      <div className="panel-header">
        <ChannelBadge tabId={tabId} />
        <span>IDA View</span>
        <div className="hex-addr-input-wrap">
          <input
            className="hex-addr-input"
            value={addrInput}
            onChange={(e) => setAddrInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleGo()}
            placeholder="Go to address..."
          />
        </div>
      </div>
      <div
        className="panel-body code-panel-body linear-body"
        ref={containerRef}
        onScroll={handleScroll}
      >
        {lines.length === 0 && !loading && (
          <div className="empty-hint">No data loaded</div>
        )}
        <div className="code-lines">
          {lines.map((line, idx) => (
            <LinearLineRow
              key={`${line.addr}-${idx}`}
              line={line}
              highlightToken={highlightToken}
              isAddrHighlighted={highlightDisasmAddrs.includes(line.addr)}
              onClick={handleClick}
            />
          ))}
        </div>
        {loading && <div className="linear-loading">Loading...</div>}
      </div>
    </div>
  );
}

function LinearLineRow({
  line, highlightToken, isAddrHighlighted, onClick,
}: {
  line: LinearLine;
  highlightToken: string | null;
  isAddrHighlighted: boolean;
  onClick: (line: LinearLine, e: React.MouseEvent) => void;
}) {
  const hlClass = isAddrHighlighted ? " code-line-hl" : "";

  switch (line.type) {
    case "separator":
      return <div className="linear-separator" />;
    case "func_header":
      return (
        <div className={`code-line linear-func-header${hlClass}`} onClick={(e) => onClick(line, e)}>
          <span className="linear-seg">{line.segment}</span>
          <span className="linear-addr">{line.addr}</span>
          <span className="linear-func-name" data-token={line.func_name}>{line.text}</span>
        </div>
      );
    case "func_end":
      return (
        <div className="code-line linear-func-end">
          <span className="linear-seg" />
          <span className="linear-addr">{line.addr}</span>
          <span className="linear-text-muted">{line.text}</span>
        </div>
      );
    case "xref_comment":
      return (
        <div className="code-line linear-xref">
          <span className="linear-seg" />
          <span className="linear-addr" />
          <span className="hl-comment">{line.text}</span>
        </div>
      );
    case "code":
      return (
        <div className={`code-line${hlClass}`} data-addr={line.addr} onClick={(e) => onClick(line, e)}>
          <span className="linear-seg">{line.segment}</span>
          <span className="linear-addr">{line.addr}</span>
          <span
            className={`disasm-mnem${highlightToken === line.mnemonic ? " token-hl" : ""}`}
            data-token={line.mnemonic}
          >{line.mnemonic}</span>
          <span className="disasm-ops">{highlightOps(line.operands || "", highlightToken)}</span>
        </div>
      );
    case "data":
    case "string":
      return (
        <div className={`code-line${hlClass}`} data-addr={line.addr} onClick={(e) => onClick(line, e)}>
          <span className="linear-seg">{line.segment}</span>
          <span className="linear-addr">{line.addr}</span>
          {line.name && <span className="linear-name" data-token={line.name}>{line.name} </span>}
          <span className={line.type === "string" ? "hl-str" : "linear-data"}>{line.text}</span>
        </div>
      );
    case "align":
      return (
        <div className="code-line linear-align">
          <span className="linear-seg">{line.segment}</span>
          <span className="linear-addr">{line.addr}</span>
          <span className="linear-text-muted">{line.text}</span>
        </div>
      );
    default: {
      const collapsed = (line.size || 0) > 1;
      return (
        <div className={`code-line ${collapsed ? "linear-collapsed" : "linear-unknown"}`}>
          <span className="linear-seg">{line.segment}</span>
          <span className="linear-addr">{line.addr}</span>
          {collapsed ? (
            <>
              <span className="collapsed-badge">{line.size} bytes</span>
              <span className="linear-text-muted">{line.text}</span>
            </>
          ) : (
            <span className="linear-text-muted">{line.text}</span>
          )}
        </div>
      );
    }
  }
}
