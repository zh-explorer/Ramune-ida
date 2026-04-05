import { useCallback, useEffect, useState } from "react";
import { xrefs } from "../api/client";
import { useProjectStore } from "../stores/projectStore";
import { useViewStore } from "../stores/viewStore";
import { ChannelBadge } from "../components/ChannelBadge";

interface XrefEntry {
  addr: string;
  text: string;
}

function parseXrefs(raw: string): XrefEntry[] {
  if (!raw) return [];
  return raw.split("\n").filter(Boolean).map((line) => {
    const addr = line.match(/^(0x[0-9a-fA-F]+)/)?.[1] || "";
    return { addr, text: line };
  });
}

export function XrefsList({ tabId = "xrefs" }: { tabId?: string }) {
  const { activeProjectId } = useProjectStore();
  const store = useViewStore();
  const ch = store.getTabChannel(tabId);
  const channel = store.getChannel(ch);
  const { targetAddr, currentFunc } = channel;

  const [entries, setEntries] = useState<XrefEntry[]>([]);
  const [queryAddr, setQueryAddr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [addrInput, setAddrInput] = useState("");

  const activate = useCallback(() => store.setActiveChannel(ch), [store, ch]);

  // Auto-load xrefs when targetAddr or currentFunc changes
  const addr = targetAddr || currentFunc;
  useEffect(() => {
    if (!activeProjectId || !addr) return;
    if (addr === queryAddr) return; // Already loaded
    setLoading(true);
    setQueryAddr(addr);
    xrefs(activeProjectId, addr)
      .then((res) => {
        const raw = (res as Record<string, unknown>).xrefs as string || "";
        setEntries(parseXrefs(raw));
      })
      .catch(() => setEntries([]))
      .finally(() => setLoading(false));
  }, [activeProjectId, addr, queryAddr]);

  const handleGo = useCallback(() => {
    if (!activeProjectId || !addrInput) return;
    setLoading(true);
    setQueryAddr(addrInput);
    xrefs(activeProjectId, addrInput)
      .then((res) => {
        const raw = (res as Record<string, unknown>).xrefs as string || "";
        setEntries(parseXrefs(raw));
      })
      .catch(() => setEntries([]))
      .finally(() => setLoading(false));
    setAddrInput("");
  }, [activeProjectId, addrInput]);

  const handleClick = useCallback(
    (entry: XrefEntry) => {
      if (activeProjectId && entry.addr) {
        store.navigateTo(ch, activeProjectId, entry.addr);
      }
    },
    [store, ch, activeProjectId],
  );

  return (
    <div className="panel xrefs-panel" onMouseDown={activate}>
      <div className="panel-header">
        <ChannelBadge tabId={tabId} />
        <span>Xrefs{queryAddr ? `: ${queryAddr}` : ""}</span>
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
      <div className="panel-body">
        {loading && <div className="empty-hint">Loading...</div>}
        {!loading && entries.length === 0 && (
          <div className="empty-hint">No cross-references</div>
        )}
        {!loading && entries.length > 0 && (
          <div className="xrefs-list">
            <div className="xrefs-count">{entries.length} reference{entries.length !== 1 ? "s" : ""}</div>
            {entries.map((entry, i) => (
              <div
                key={i}
                className="xref-item"
                onClick={() => handleClick(entry)}
              >
                <span className="xref-addr">{entry.addr}</span>
                <span className="xref-text">{entry.text.replace(entry.addr, "").trim()}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
