import { useCallback, useEffect, useState } from "react";
import { useProjectStore } from "../stores/projectStore";
import { useViewStore } from "../stores/viewStore";
import { ChannelBadge } from "../components/ChannelBadge";

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

  const activate = useCallback(() => store.setActiveChannel(ch), [store, ch]);

  // Load bytes from an address
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

  // Follow channel's targetAddr (navigation jumps)
  useEffect(() => {
    if (targetAddr) loadAddr(targetAddr);
  }, [targetAddr, loadAddr]);

  // Follow highlight sync (click in other panels)
  useEffect(() => {
    if (highlightDisasmAddrs.length > 0) loadAddr(highlightDisasmAddrs[0]);
  }, [highlightDisasmAddrs, loadAddr]);

  const handleGo = () => {
    if (addrInput) loadAddr(addrInput);
  };

  const rows: number[][] = [];
  for (let i = 0; i < bytes.length; i += BYTES_PER_ROW) {
    rows.push(bytes.slice(i, i + BYTES_PER_ROW));
  }

  // Which byte offset is highlighted?
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
          <table className="hex-table">
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
                        const byteOffset = rowIdx * BYTES_PER_ROW + i;
                        const isHl = highlightOffset >= 0 &&
                          byteOffset >= highlightOffset &&
                          byteOffset < highlightOffset + 16;
                        return (
                          <span key={i} className={`hex-byte${isHl ? " hex-byte-hl" : ""}`}>
                            {formatHex(b)}
                          </span>
                        );
                      })}
                    </td>
                    <td className="hex-ascii">
                      {row.map((b, i) => (
                        <span key={i}>{formatAscii(b)}</span>
                      ))}
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
