import { useViewStore } from "../stores/viewStore";

const CHANNEL_COLORS: Record<string, string> = {
  A: "#89b4fa", B: "#a6e3a1", C: "#fab387", D: "#f38ba8", E: "#cba6f7",
};

const SYNCABLE = new Set(["decompile", "disassembly", "idaview"]);

const TYPE_LABELS: Record<string, string> = {
  decompile: "Decompile",
  disassembly: "Disassembly",
  idaview: "IDA View",
  functions: "Functions",
  strings: "Strings",
  hex: "Hex",
  project: "Project",
  activity: "Activity",
};

function parseType(tabId: string): string {
  const colon = tabId.indexOf(":");
  return colon >= 0 ? tabId.substring(0, colon) : tabId;
}

export function TabTitle({ tabId }: { tabId: string }) {
  const tabChannels = useViewStore((s) => s.tabChannels);
  const type = parseType(tabId);
  const base = TYPE_LABELS[type] || type;

  // Count same-type tabs for suffix
  const sameType = Object.keys(tabChannels).filter((t) => parseType(t) === type);
  const suffix = sameType.length > 1
    ? `-${sameType.sort().indexOf(tabId) + 1}`
    : "";

  if (!SYNCABLE.has(type)) {
    return <>{base}{suffix}</>;
  }

  const ch = tabChannels[tabId] || "A";
  const color = CHANNEL_COLORS[ch] || "#666";

  return (
    <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
      <span style={{
        width: 6, height: 6, borderRadius: "50%",
        background: color, flexShrink: 0,
      }} />
      {base}{suffix}
    </span>
  );
}
