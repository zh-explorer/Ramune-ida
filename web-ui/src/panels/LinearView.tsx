import { useCallback, useEffect, useRef, useState } from "react";
import { linearView } from "../api/client";
import { useProjectStore } from "../stores/projectStore";
import { useViewStore } from "../stores/viewStore";
import { highlightOps } from "../utils/highlightAsm";
import { isNavigable } from "../utils/codeNav";
import { ChannelBadge } from "../components/ChannelBadge";
import { useCodeContextMenu } from "../hooks/useCodeContextMenu";
import type { LinearLine } from "../api/types";

const CHUNK_SIZE = 150;
const LOAD_THRESHOLD = 300; // px from edge
const MAX_LINES = 3000;     // GC threshold: clear and rebuild

export function LinearView({ tabId = "idaview" }: { tabId?: string }) {
  const { activeProjectId } = useProjectStore();
  const store = useViewStore();
  const ch = store.getTabChannel(tabId);
  const channel = store.getChannel(ch);
  const { highlightToken, highlightDisasmAddrs, targetAddr, funcData } = channel;

  const [lines, setLines] = useState<LinearLine[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasMoreTop, setHasMoreTop] = useState(true);
  const [hasMoreBottom, setHasMoreBottom] = useState(true);
  const [addrInput, setAddrInput] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const loadingRef = useRef(false);

  const activate = useCallback(() => store.setActiveChannel(ch), [store, ch]);
  const onContextMenu = useCodeContextMenu(ch);

  // ── Core load functions ────────────────────────────────────

  /** Load forward from addr, replace or append */
  const loadForward = useCallback(
    async (addr: string, append = false) => {
      if (!activeProjectId || loadingRef.current) return;
      loadingRef.current = true;
      setLoading(true);
      try {
        const data = await linearView(activeProjectId, addr, CHUNK_SIZE, "forward");
        if (append) {
          setLines((prev) => {
            // Deduplicate by addr
            const existing = new Set(prev.map((l) => l.addr).filter(Boolean));
            const newLines = data.lines.filter((l) => !l.addr || !existing.has(l.addr));
            return [...prev, ...newLines];
          });
        } else {
          setLines(data.lines);
          setHasMoreTop(true);
        }
        setHasMoreBottom(data.has_more);
      } catch { /* ignore */ }
      finally { setLoading(false); loadingRef.current = false; }
    },
    [activeProjectId],
  );

  /** Load backward from addr, prepend */
  const loadBackward = useCallback(
    async (addr: string) => {
      if (!activeProjectId || loadingRef.current) return;
      loadingRef.current = true;
      setLoading(true);
      try {
        const data = await linearView(activeProjectId, addr, CHUNK_SIZE, "backward");
        if (data.lines.length > 0) {
          const el = containerRef.current;
          const prevScrollHeight = el?.scrollHeight || 0;
          const prevScrollTop = el?.scrollTop || 0;

          setLines((prev) => {
            const existing = new Set(prev.map((l) => l.addr).filter(Boolean));
            const newLines = data.lines.filter((l) => !l.addr || !existing.has(l.addr));
            return [...newLines, ...prev];
          });

          // Fix scroll position after prepend
          requestAnimationFrame(() => {
            if (el) {
              el.scrollTop = prevScrollTop + (el.scrollHeight - prevScrollHeight);
            }
          });
        }
        setHasMoreTop(data.has_more);
      } catch { /* ignore */ }
      finally { setLoading(false); loadingRef.current = false; }
    },
    [activeProjectId],
  );

  /** Jump to addr: clear everything, load forward + backward around target */
  const jumpTo = useCallback(
    async (addr: string) => {
      if (!activeProjectId) return;
      // GC: clear existing data
      setLines([]);
      setHasMoreTop(true);
      setHasMoreBottom(true);
      loadingRef.current = false;

      // Load forward from addr
      loadingRef.current = true;
      setLoading(true);
      try {
        // Load forward
        const fwd = await linearView(activeProjectId, addr, CHUNK_SIZE, "forward");
        // Load backward
        const bwd = await linearView(activeProjectId, addr, CHUNK_SIZE / 2, "backward");

        // Merge: backward lines (excluding addr itself) + forward lines
        const fwdAddrs = new Set(fwd.lines.map((l) => l.addr).filter(Boolean));
        const bwdFiltered = bwd.lines.filter((l) => !l.addr || !fwdAddrs.has(l.addr));

        setLines([...bwdFiltered, ...fwd.lines]);
        setHasMoreTop(bwd.has_more);
        setHasMoreBottom(fwd.has_more);
      } catch { /* ignore */ }
      finally { setLoading(false); loadingRef.current = false; }

      // Scroll to target after render
      requestAnimationFrame(() => {
        containerRef.current
          ?.querySelector(`[data-addr="${addr}"]`)
          ?.scrollIntoView({ block: "center", behavior: "auto" });
      });
    },
    [activeProjectId],
  );

  // ── Initial load ───────────────────────────────────────────

  useEffect(() => {
    if (!activeProjectId) { setLines([]); return; }
    jumpTo("0x0");
  }, [activeProjectId]); // eslint-disable-line

  // ── Sync: follow targetAddr ────────────────────────────────

  useEffect(() => {
    if (!targetAddr) return;
    const el = containerRef.current?.querySelector(`[data-addr="${targetAddr}"]`);
    if (el) {
      // Already loaded — check if visible
      const rect = el.getBoundingClientRect();
      const cRect = containerRef.current!.getBoundingClientRect();
      if (rect.top < cRect.top || rect.bottom > cRect.bottom) {
        el.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    } else {
      // Not loaded — jump (clear + reload around target)
      jumpTo(targetAddr);
    }
  }, [targetAddr]); // eslint-disable-line

  // ── Sync: follow highlight ─────────────────────────────────

  useEffect(() => {
    if (highlightDisasmAddrs.length === 0 || !containerRef.current) return;
    const addr = highlightDisasmAddrs[0];
    const el = containerRef.current.querySelector(`[data-addr="${addr}"]`);
    if (el) {
      const rect = el.getBoundingClientRect();
      const cRect = containerRef.current.getBoundingClientRect();
      if (rect.top < cRect.top || rect.bottom > cRect.bottom) {
        el.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    }
    // Don't jumpTo on highlight — only on navigate
  }, [highlightDisasmAddrs]);

  // ── Scroll handler ─────────────────────────────────────────

  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el || loadingRef.current) return;

    // GC: if too many lines, jump to current center
    if (lines.length > MAX_LINES) {
      const centerIdx = Math.floor(lines.length / 2);
      const centerAddr = lines[centerIdx]?.addr;
      if (centerAddr) {
        jumpTo(centerAddr);
        return;
      }
    }

    const distBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    const distTop = el.scrollTop;

    // Near bottom — load more forward
    if (hasMoreBottom && distBottom < LOAD_THRESHOLD) {
      const lastAddr = lines[lines.length - 1]?.addr;
      if (lastAddr) {
        // Find boundary: next addr after last line
        const lastNum = parseInt(lastAddr, 16);
        const lastSize = lines[lines.length - 1]?.size || 1;
        const nextAddr = `0x${(lastNum + lastSize).toString(16)}`;
        loadForward(nextAddr, true);
      }
    }

    // Near top — load more backward
    if (hasMoreTop && distTop < LOAD_THRESHOLD) {
      const firstAddr = lines.find((l) => l.addr)?.addr;
      if (firstAddr) {
        loadBackward(firstAddr);
      }
    }
  }, [lines, hasMoreTop, hasMoreBottom, loadForward, loadBackward, jumpTo]);

  // ── Navigation ─────────────────────────────────────────────

  const handleGo = useCallback(() => {
    if (addrInput) { jumpTo(addrInput); setAddrInput(""); }
  }, [addrInput, jumpTo]);

  const handleClick = useCallback(
    (line: LinearLine, e: React.MouseEvent) => {
      activate();
      const target = (e.target as HTMLElement).getAttribute?.("data-token");

      if (e.detail === 2) {
        if (target && activeProjectId && isNavigable(target)) {
          store.navigateTo(ch, activeProjectId, target);
        }
        return;
      }

      if (target) {
        store.setHighlightToken(ch, target === highlightToken ? null : target);
      }

      // Sync address with other panels
      if (line.addr) {
        if (line.type === "code" && activeProjectId) {
          const clickedFunc = line.func_name;
          const currentFunc = funcData?.func?.name;
          if (clickedFunc && clickedFunc !== currentFunc) {
            store.navigateTo(ch, activeProjectId, line.addr);
            return;
          }
          // Code in current function — full sync with decompile
          store.highlightFromDisasm(ch, line.addr);
        } else {
          // Non-code (data, string, etc.) — just set address for Hex View
          store.setTargetAddr(ch, line.addr);
        }
      }
    },
    [store, ch, activeProjectId, highlightToken, funcData, activate],
  );

  // ── Render ─────────────────────────────────────────────────

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
        onContextMenu={onContextMenu}
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

// ── Line rendering ──────────────────────────────────────────────

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
