import { useCallback, useEffect, useState } from "react";
import { xrefs } from "../api/client";
import { useProjectStore } from "../stores/projectStore";
import { useViewStore } from "../stores/viewStore";
import { ChannelBadge } from "../components/ChannelBadge";
import { useCodeContextMenu } from "../hooks/useCodeContextMenu";

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
  const onContextMenu = useCodeContextMenu(ch);

  const doQuery = useCallback((target: string) => {
    if (!activeProjectId || !target) return;
    setLoading(true);
    setQueryAddr(target);
    xrefs(activeProjectId, target)
      .then((res) => {
        const raw = (res as Record<string, unknown>).xrefs as string || "";
        setEntries(parseXrefs(raw));
      })
      .catch(() => setEntries([]))
      .finally(() => setLoading(false));
  }, [activeProjectId]);

  // Only auto-load once on first meaningful address, not on every navigation
  const addr = targetAddr || currentFunc;
  useEffect(() => {
    if (!activeProjectId || !addr || queryAddr) return;
    doQuery(addr);
  }, [activeProjectId, addr, queryAddr, doQuery]);

  // Respond to xref requests from context menu
  const xrefRequest = store.xrefRequest;
  useEffect(() => {
    if (!xrefRequest || !activeProjectId) return;
    doQuery(xrefRequest.target);
  }, [xrefRequest, activeProjectId, doQuery]);

  const handleGo = useCallback(() => {
    if (!addrInput) return;
    doQuery(addrInput);
    setAddrInput("");
  }, [addrInput, doQuery]);

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
                onContextMenu={onContextMenu}
                data-addr={entry.addr}
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
