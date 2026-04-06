import { useCallback, useEffect, useRef, useState } from "react";
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

const BYTES_PER_ROW = 16;
const DEFAULT_SIZE = 256;

function formatHex(byte: number): string {
  return byte.toString(16).padStart(2, "0");
}

function formatAscii(byte: number): string {
  return byte >= 0x20 && byte < 0x7f ? String.fromCharCode(byte) : ".";
}

function parseHexString(hex: string): number[] {
  const bytes: number[] = [];
  for (let i = 0; i < hex.length; i += 2) {
    bytes.push(parseInt(hex.substring(i, i + 2), 16));
  }
  return bytes;
}

async function fetchBytes(
  pid: string,
  addr: string,
  size: number,
): Promise<{ addr: string; bytes: number[] }> {
  const res = await fetch(
    `/api/projects/${pid}/bytes?addr=${encodeURIComponent(addr)}&size=${size}`,
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  return { addr: data.addr, bytes: parseHexString(data.bytes || "") };
}

export function HexView({ tabId = "hex" }: { tabId?: string }) {
  const { activeProjectId } = useProjectStore();
  const store = useViewStore();
  const ch = store.getTabChannel(tabId);
  const channel = store.getChannel(ch);
  const { targetAddr, highlightDisasmAddrs } = channel;

  const [bytes, setBytes] = useState<number[]>([]);
  const [baseAddr, setBaseAddr] = useState<number>(0);
  const [loading, setLoading] = useState(false);
  const [addrInput, setAddrInput] = useState("");

  // Selection state: [start, end] byte offsets (inclusive)
  const [selStart, setSelStart] = useState<number | null>(null);
  const [selEnd, setSelEnd] = useState<number | null>(null);
  const dragging = useRef(false);

  const activate = useCallback(() => store.setActiveChannel(ch), [store, ch]);

  const loadAddr = useCallback(
    (addr: string) => {
      if (!activeProjectId) return;
      setLoading(true);
      fetchBytes(activeProjectId, addr, DEFAULT_SIZE)
        .then((data) => {
          setBytes(data.bytes);
          setBaseAddr(parseInt(data.addr, 16) || 0);
          setAddrInput(data.addr);
        })
        .catch(() => setBytes([]))
        .finally(() => setLoading(false));
    },
    [activeProjectId],
  );

  useEffect(() => {
    if (targetAddr) loadAddr(targetAddr);
  }, [targetAddr, loadAddr]);

  useEffect(() => {
    if (highlightDisasmAddrs.length > 0) loadAddr(highlightDisasmAddrs[0]);
  }, [highlightDisasmAddrs, loadAddr]);

  const handleGo = () => {
    if (addrInput) loadAddr(addrInput);
  };

  // Mouse selection handlers
  const onByteMouseDown = useCallback((offset: number, e: React.MouseEvent) => {
    if (e.button === 2) return; // right-click handled by onContextMenu
    e.preventDefault();
    dragging.current = true;
    setSelStart(offset);
    setSelEnd(offset);
  }, []);

  const onByteMouseEnter = useCallback((offset: number) => {
    if (dragging.current) {
      setSelEnd(offset);
    }
  }, []);

  useEffect(() => {
    const onMouseUp = () => { dragging.current = false; };
    window.addEventListener("mouseup", onMouseUp);
    return () => window.removeEventListener("mouseup", onMouseUp);
  }, []);

  // Compute selected range
  const selMin = selStart !== null && selEnd !== null ? Math.min(selStart, selEnd) : -1;
  const selMax = selStart !== null && selEnd !== null ? Math.max(selStart, selEnd) : -1;

  const getSelectedBytes = useCallback((): number[] => {
    if (selMin < 0 || selMax < 0) return [];
    return bytes.slice(selMin, selMax + 1);
  }, [bytes, selMin, selMax]);

  const onContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const sel = getSelectedBytes();
    if (sel.length === 0) return;

    const addr = baseAddr + selMin;
    const items: ContextMenuItem[] = [
      {
        label: `Copy address (0x${addr.toString(16)})`,
        onClick: () => copyText("0x" + addr.toString(16)),
      },
      { label: "", onClick: () => {}, separator: true },
      {
        label: `Copy hex (${sel.length} bytes)`,
        onClick: () => copyText(sel.map((b) => formatHex(b).toUpperCase()).join(" ")),
      },
      {
        label: "Copy as hex string",
        onClick: () => copyText(sel.map((b) => formatHex(b)).join("")),
      },
      {
        label: "Copy as C array",
        onClick: () => {
          const inner = sel.map((b) => "0x" + formatHex(b).toUpperCase()).join(", ");
          copyText(`{ ${inner} }`);
        },
      },
      {
        label: "Copy as Python bytes",
        onClick: () => copyText(`b'${sel.map((b) => "\\x" + formatHex(b)).join("")}'`),
      },
      {
        label: "Copy as ASCII",
        onClick: () => copyText(sel.map((b) => formatAscii(b)).join("")),
      },
      {
        label: "Copy as IDA pattern",
        onClick: () => copyText(sel.map((b) => formatHex(b).toUpperCase()).join(" ")),
      },
    ];

    showContextMenu(e.clientX, e.clientY, items);
  }, [getSelectedBytes, baseAddr, selMin]);

  const rows: number[][] = [];
  for (let i = 0; i < bytes.length; i += BYTES_PER_ROW) {
    rows.push(bytes.slice(i, i + BYTES_PER_ROW));
  }

  const highlightOffset = highlightDisasmAddrs.length > 0
    ? parseInt(highlightDisasmAddrs[0], 16) - baseAddr
    : -1;

  return (
    <div className="panel hex-panel" onMouseDown={activate}>
      <div className="panel-header">
        <ChannelBadge tabId={tabId} />
        <span>Hex</span>
        <div className="hex-addr-input-wrap">
          <input
            className="hex-addr-input"
            value={addrInput}
            onChange={(e) => setAddrInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleGo()}
            placeholder="Address..."
          />
        </div>
      </div>
      <div className="panel-body hex-body">
        {loading && <div className="empty-hint">Loading...</div>}
        {!loading && bytes.length === 0 && (
          <div className="empty-hint">No data</div>
        )}
        {!loading && rows.length > 0 && (
          <table className="hex-table" onContextMenu={onContextMenu}>
            <tbody>
              {rows.map((row, rowIdx) => {
                const addr = baseAddr + rowIdx * BYTES_PER_ROW;
                return (
                  <tr key={rowIdx}>
                    <td className="hex-addr">
                      {addr.toString(16).padStart(8, "0")}
                    </td>
                    <td className="hex-bytes">
                      {row.map((b, i) => {
                        const offset = rowIdx * BYTES_PER_ROW + i;
                        const isHl = highlightOffset >= 0 &&
                          offset >= highlightOffset &&
                          offset < highlightOffset + 16;
                        const isSel = offset >= selMin && offset <= selMax;
                        return (
                          <span
                            key={i}
                            className={`hex-byte${isHl ? " hex-byte-hl" : ""}${isSel ? " hex-byte-sel" : ""}`}
                            onMouseDown={(e) => onByteMouseDown(offset, e)}
                            onMouseEnter={() => onByteMouseEnter(offset)}
                          >
                            {formatHex(b)}
                          </span>
                        );
                      })}
                    </td>
                    <td className="hex-ascii">
                      {row.map((b, i) => {
                        const offset = rowIdx * BYTES_PER_ROW + i;
                        const isSel = offset >= selMin && offset <= selMax;
                        return (
                          <span
                            key={i}
                            className={isSel ? "hex-ascii-sel" : ""}
                            onMouseDown={(e) => onByteMouseDown(offset, e)}
                            onMouseEnter={() => onByteMouseEnter(offset)}
                          >
                            {formatAscii(b)}
                          </span>
                        );
                      })}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
