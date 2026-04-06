import { useCallback, useEffect, useRef, useState } from "react";
import { hexView } from "../api/client";
import { useProjectStore } from "../stores/projectStore";
import { useViewStore } from "../stores/viewStore";
import { ChannelBadge } from "../components/ChannelBadge";
import { showContextMenu, type ContextMenuItem } from "../components/ContextMenu";

function copyText(text: string) {
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text);
  } else {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
  }
}

const PER_ROW = 16;
const CHUNK_ROWS = 32;
const LOAD_THRESHOLD = 200;
const MAX_ROWS = 2000;

function fmtHex(b: number) { return b.toString(16).padStart(2, "0"); }
function fmtAscii(b: number) { return b >= 0x20 && b < 0x7f ? String.fromCharCode(b) : "."; }

interface HexRow {
  addr: string;   // "0x1000"
  addrNum: number;
  bytes: number[]; // 16 entries
}

function parseRow(raw: { addr: string; hex: string }): HexRow {
  const bytes: number[] = [];
  for (let i = 0; i < raw.hex.length; i += 2)
    bytes.push(parseInt(raw.hex.substring(i, i + 2), 16));
  while (bytes.length < PER_ROW) bytes.push(0);
  return { addr: raw.addr, addrNum: parseInt(raw.addr, 16), bytes };
}

export function HexView({ tabId = "hex" }: { tabId?: string }) {
  const { activeProjectId } = useProjectStore();
  const store = useViewStore();
  const ch = store.getTabChannel(tabId);
  const channel = store.getChannel(ch);
  const { targetAddr, highlightDisasmAddrs } = channel;

  const containerRef = useRef<HTMLDivElement>(null);
  const [rows, setRows] = useState<HexRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasMoreTop, setHasMoreTop] = useState(true);
  const [hasMoreBottom, setHasMoreBottom] = useState(true);
  const [addrInput, setAddrInput] = useState("");
  const loadingRef = useRef(false);

  // Selection
  const [selStart, setSelStart] = useState<number | null>(null);
  const [selEnd, setSelEnd] = useState<number | null>(null);
  const dragging = useRef(false);
  const selMin = selStart !== null && selEnd !== null ? Math.min(selStart, selEnd) : -1;
  const selMax = selStart !== null && selEnd !== null ? Math.max(selStart, selEnd) : -1;

  const activate = useCallback(() => store.setActiveChannel(ch), [store, ch]);

  // ── Load forward ──
  const loadForward = useCallback(async (addr: string, append = false) => {
    if (!activeProjectId || loadingRef.current) return;
    loadingRef.current = true;
    setLoading(true);
    try {
      const data = await hexView(activeProjectId, addr, CHUNK_ROWS, "forward");
      const newRows = data.rows.map(parseRow);
      if (append) {
        setRows((prev) => {
          const existing = new Set(prev.map((r) => r.addr));
          return [...prev, ...newRows.filter((r) => !existing.has(r.addr))];
        });
      } else {
        setRows(newRows);
        setHasMoreTop(true);
      }
      setHasMoreBottom(data.has_more);
    } catch {}
    finally { setLoading(false); loadingRef.current = false; }
  }, [activeProjectId]);

  // ── Load backward ──
  const loadBackward = useCallback(async (addr: string) => {
    if (!activeProjectId || loadingRef.current) return;
    loadingRef.current = true;
    setLoading(true);
    try {
      const data = await hexView(activeProjectId, addr, CHUNK_ROWS, "backward");
      const newRows = data.rows.map(parseRow);
      if (newRows.length > 0) {
        const el = containerRef.current;
        const prevH = el?.scrollHeight || 0;
        const prevT = el?.scrollTop || 0;

        setRows((prev) => {
          const existing = new Set(prev.map((r) => r.addr));
          return [...newRows.filter((r) => !existing.has(r.addr)), ...prev];
        });

        requestAnimationFrame(() => {
          if (el) el.scrollTop = prevT + (el.scrollHeight - prevH);
        });
      }
      setHasMoreTop(data.has_more);
    } catch {}
    finally { setLoading(false); loadingRef.current = false; }
  }, [activeProjectId]);

  // ── Jump to ──
  const jumpTo = useCallback(async (addr: string) => {
    if (!activeProjectId) return;
    setRows([]);
    setHasMoreTop(true);
    setHasMoreBottom(true);
    loadingRef.current = false;

    loadingRef.current = true;
    setLoading(true);
    try {
      const fwd = await hexView(activeProjectId, addr, CHUNK_ROWS, "forward");
      const bwd = await hexView(activeProjectId, addr, CHUNK_ROWS / 2, "backward");

      const fwdRows = fwd.rows.map(parseRow);
      const bwdRows = bwd.rows.map(parseRow);
      const fwdAddrs = new Set(fwdRows.map((r) => r.addr));
      const merged = [...bwdRows.filter((r) => !fwdAddrs.has(r.addr)), ...fwdRows];

      setRows(merged);
      setHasMoreTop(bwd.has_more);
      setHasMoreBottom(fwd.has_more);
    } catch {}
    finally { setLoading(false); loadingRef.current = false; }

    setAddrInput(addr);
    requestAnimationFrame(() => {
      const aligned = "0x" + (parseInt(addr, 16) & ~0xF).toString(16);
      containerRef.current
        ?.querySelector(`[data-addr="${aligned}"]`)
        ?.scrollIntoView({ block: "center", behavior: "auto" });
    });
  }, [activeProjectId]);

  // ── Initial load ──
  useEffect(() => {
    if (!activeProjectId) { setRows([]); return; }
    jumpTo("0x0");
  }, [activeProjectId]); // eslint-disable-line

  // ── Follow targetAddr ──
  useEffect(() => {
    if (!targetAddr) return;
    const aligned = "0x" + (parseInt(targetAddr, 16) & ~0xF).toString(16);
    const el = containerRef.current?.querySelector(`[data-addr="${aligned}"]`);

    if (!el && rows.length > 0) {
      const tNum = parseInt(targetAddr, 16);
      const first = rows[0].addrNum;
      const last = rows[rows.length - 1].addrNum;
      // Find closest row if within range
      if (tNum >= first && tNum <= last + PER_ROW) {
        let closest: HexRow | null = null;
        for (const r of rows) {
          if (r.addrNum <= tNum) closest = r;
          else break;
        }
        if (closest) {
          containerRef.current
            ?.querySelector(`[data-addr="${closest.addr}"]`)
            ?.scrollIntoView({ block: "center", behavior: "smooth" });
          return;
        }
      }
    }

    if (el) {
      const rect = el.getBoundingClientRect();
      const cRect = containerRef.current!.getBoundingClientRect();
      if (rect.top < cRect.top || rect.bottom > cRect.bottom) {
        el.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    } else {
      jumpTo(targetAddr);
    }
  }, [targetAddr]); // eslint-disable-line

  // ── Scroll handler ──
  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el || loadingRef.current || rows.length === 0) return;

    // GC
    if (rows.length > MAX_ROWS) {
      const center = rows[Math.floor(rows.length / 2)];
      jumpTo(center.addr);
      return;
    }

    const distBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    const distTop = el.scrollTop;

    if (hasMoreBottom && distBottom < LOAD_THRESHOLD) {
      const lastRow = rows[rows.length - 1];
      const nextAddr = "0x" + (lastRow.addrNum + PER_ROW).toString(16);
      loadForward(nextAddr, true);
    }
    if (hasMoreTop && distTop < LOAD_THRESHOLD) {
      loadBackward(rows[0].addr);
    }
  }, [rows, hasMoreTop, hasMoreBottom, loadForward, loadBackward, jumpTo]);

  const handleGo = () => {
    if (addrInput) { jumpTo(addrInput); setAddrInput(""); }
  };

  // ── Selection ──
  const onByteMouseDown = useCallback((addr: number, e: React.MouseEvent) => {
    if (e.button === 2) return;
    e.preventDefault();
    dragging.current = true;
    setSelStart(addr);
    setSelEnd(addr);
  }, []);
  const onByteMouseEnter = useCallback((addr: number) => {
    if (dragging.current) setSelEnd(addr);
  }, []);
  useEffect(() => {
    const up = () => { dragging.current = false; };
    window.addEventListener("mouseup", up);
    return () => window.removeEventListener("mouseup", up);
  }, []);

  // ── Context menu ──
  const onContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    if (selMin < 0) return;
    const sel: number[] = [];
    for (const row of rows) {
      for (let i = 0; i < PER_ROW; i++) {
        const ba = row.addrNum + i;
        if (ba >= selMin && ba <= selMax) sel.push(row.bytes[i]);
      }
    }
    if (!sel.length) return;
    const items: ContextMenuItem[] = [
      { label: `Copy address (0x${selMin.toString(16)})`, onClick: () => copyText("0x" + selMin.toString(16)) },
      { label: "", onClick: () => {}, separator: true },
      { label: `Copy hex (${sel.length} bytes)`, onClick: () => copyText(sel.map((b) => fmtHex(b).toUpperCase()).join(" ")) },
      { label: "Copy as hex string", onClick: () => copyText(sel.map((b) => fmtHex(b)).join("")) },
      { label: "Copy as C array", onClick: () => copyText(`{ ${sel.map((b) => "0x" + fmtHex(b).toUpperCase()).join(", ")} }`) },
      { label: "Copy as Python bytes", onClick: () => copyText(`b'${sel.map((b) => "\\x" + fmtHex(b)).join("")}'`) },
      { label: "Copy as ASCII", onClick: () => copyText(sel.map((b) => fmtAscii(b)).join("")) },
    ];
    showContextMenu(e.clientX, e.clientY, items);
  }, [selMin, selMax, rows]);

  const hlAddr = highlightDisasmAddrs.length > 0 ? parseInt(highlightDisasmAddrs[0], 16) : -1;

  return (
    <div className="panel hex-panel" onMouseDown={activate} tabIndex={-1}>
      <div className="panel-header">
        <ChannelBadge tabId={tabId} />
        <span>Hex</span>
        <div className="hex-addr-input-wrap">
          <input className="hex-addr-input" value={addrInput}
            onChange={(e) => setAddrInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleGo()}
            placeholder="Address..." />
        </div>
      </div>
      <div className="panel-body hex-body" ref={containerRef} onScroll={handleScroll} onContextMenu={onContextMenu}>
        {rows.length === 0 && !loading && <div className="empty-hint">No data</div>}
        <table className="hex-table">
          <tbody>
            {rows.map((row) => (
              <tr key={row.addr} data-addr={row.addr}>
                <td className="hex-addr">{row.addrNum.toString(16).padStart(8, "0")}</td>
                <td className="hex-bytes">
                  {row.bytes.map((b, i) => {
                    const ba = row.addrNum + i;
                    const isHl = hlAddr >= 0 && ba >= hlAddr && ba < hlAddr + PER_ROW;
                    const isSel = ba >= selMin && ba <= selMax;
                    return (
                      <span key={i}
                        className={`hex-byte${isHl ? " hex-byte-hl" : ""}${isSel ? " hex-byte-sel" : ""}`}
                        onMouseDown={(e) => onByteMouseDown(ba, e)}
                        onMouseEnter={() => onByteMouseEnter(ba)}
                      >{fmtHex(b)}</span>
                    );
                  })}
                </td>
                <td className="hex-ascii">
                  {row.bytes.map((b, i) => {
                    const ba = row.addrNum + i;
                    const isSel = ba >= selMin && ba <= selMax;
                    return (
                      <span key={i}
                        className={isSel ? "hex-ascii-sel" : ""}
                        onMouseDown={(e) => onByteMouseDown(ba, e)}
                        onMouseEnter={() => onByteMouseEnter(ba)}
                      >{fmtAscii(b)}</span>
                    );
                  })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {loading && <div className="linear-loading">Loading...</div>}
      </div>
    </div>
  );
}
