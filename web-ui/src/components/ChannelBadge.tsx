import { useCallback, useMemo, useState } from "react";
import { useViewStore } from "../stores/viewStore";

const CHANNEL_COLORS: Record<string, string> = {
  A: "#89b4fa", B: "#a6e3a1", C: "#fab387", D: "#f38ba8", E: "#cba6f7",
};

function colorOf(ch: string): string {
  return CHANNEL_COLORS[ch] || "#666";
}

const SYNCABLE = new Set(["decompile", "disassembly", "idaview"]);

function parseType(tabId: string): string {
  const colon = tabId.indexOf(":");
  return colon >= 0 ? tabId.substring(0, colon) : tabId;
}

const TYPE_LABELS: Record<string, string> = {
  decompile: "Decompile",
  disassembly: "Disassembly",
  idaview: "IDA View",
};

/** Build display names: same-type panels get -1, -2 suffix */
function buildNames(tabChannels: Record<string, string>): Record<string, string> {
  const byType: Record<string, string[]> = {};
  for (const id of Object.keys(tabChannels)) {
    const type = parseType(id);
    if (!SYNCABLE.has(type)) continue;
    byType[type] = byType[type] || [];
    byType[type].push(id);
  }

  const names: Record<string, string> = {};
  for (const [type, ids] of Object.entries(byType)) {
    const base = TYPE_LABELS[type] || type;
    if (ids.length === 1) {
      names[ids[0]] = base;
    } else {
      ids.forEach((id, i) => {
        names[id] = `${base}-${i + 1}`;
      });
    }
  }
  return names;
}

interface Props {
  tabId: string;
}

export function ChannelBadge({ tabId }: Props) {
  const store = useViewStore();
  const myChannel = store.getTabChannel(tabId);
  const color = colorOf(myChannel);
  const [open, setOpen] = useState(false);

  const names = useMemo(
    () => buildNames(store.tabChannels),
    [store.tabChannels],
  );

  // Other syncable tabs
  const others = useMemo(() => {
    return Object.keys(store.tabChannels)
      .filter((id) => id !== tabId && SYNCABLE.has(parseType(id)))
      .map((id) => ({
        id,
        ch: store.getTabChannel(id),
        label: names[id] || id,
      }));
  }, [store.activeTabs, store.tabChannels, tabId, names]);

  // Am I linked?
  const linkedTo = useMemo(
    () => others.find((t) => t.ch === myChannel),
    [others, myChannel],
  );

  const handleLink = useCallback(
    (targetId: string) => {
      const targetCh = store.getTabChannel(targetId);
      store.setTabChannel(tabId, targetCh);
      store.setActiveChannel(targetCh);
      setOpen(false);
    },
    [store, tabId],
  );

  const handleUnlink = useCallback(() => {
    const used = new Set(Object.values(store.tabChannels));
    const free = Object.keys(CHANNEL_COLORS).find((ch) => !used.has(ch)) || `X${Date.now()}`;
    store.setTabChannel(tabId, free);
    setOpen(false);
  }, [store, tabId]);

  return (
    <div className="channel-wrap">
      <div
        className={`channel-indicator ${linkedTo ? "linked" : "unlinked"}`}
        onClick={() => setOpen(!open)}
        title={linkedTo ? `Linked to ${linkedTo.label}` : "Not linked"}
      >
        <span className="channel-icon">{linkedTo ? "🔗" : "⛓️"}</span>
      </div>
      {linkedTo && <div className="channel-strip" style={{ background: color }} />}
      {open && (
        <div className="channel-menu" onMouseLeave={() => setOpen(false)}>
          <div className="channel-menu-title">Link to</div>
          {others.map((t) => (
            <button
              key={t.id}
              className={`channel-menu-item ${t.ch === myChannel ? "active" : ""}`}
              onClick={() => t.ch === myChannel ? handleUnlink() : handleLink(t.id)}
            >
              <span className="channel-dot" style={{ background: colorOf(t.ch) }} />
              <span>{t.label}</span>
              {t.ch === myChannel && <span className="channel-check">✓</span>}
            </button>
          ))}
          {others.length === 0 && (
            <div className="channel-menu-empty">No other panels</div>
          )}
          {linkedTo && (
            <>
              <div className="channel-menu-sep" />
              <button className="channel-menu-item" onClick={handleUnlink}>
                <span className="channel-dot" style={{ opacity: 0.3 }} />
                <span>Unlink</span>
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
