import { useCallback, useEffect, useRef, useState } from "react";
import { useActivityStore } from "../stores/activityStore";
import { useProjectStore } from "../stores/projectStore";
import { useViewStore } from "../stores/viewStore";
import type { ActivityEvent } from "../api/types";

const KIND_COLORS: Record<string, string> = {
  read: "#4fc3f7",
  write: "#ffb74d",
  unsafe: "#ef5350",
};

const STATUS_ICON: Record<string, string> = {
  pending: "⏳",
  completed: "✓",
  failed: "✗",
};

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString("en-US", { hour12: false });
}

function extractTarget(ev: ActivityEvent): string | null {
  const paramMatch = ev.params_summary.match(
    /(?:func|addr|name|target|var)=([^\s,]+)/,
  );
  if (paramMatch) return paramMatch[1];
  const hexMatch = ev.params_summary.match(/\b(0x[0-9a-fA-F]+)\b/);
  if (hexMatch) return hexMatch[1];
  return null;
}

/** Format the expanded detail section based on tool type */
function renderDetail(ev: ActivityEvent): React.ReactNode {
  const p = (ev.params || {}) as Record<string, string>;
  switch (ev.tool_name) {
    case "decompile":
      return <span>Decompile function <b>{p.func as string}</b></span>;
    case "disasm":
      return <span>Disassemble at <b>{p.addr as string}</b>{p.count ? `, ${p.count} lines` : ""}</span>;
    case "rename":
      return (
        <span>
          Rename {p.addr ? <><b>{p.addr as string}</b></> : <><b>{p.func as string}</b>:<b>{p.var as string}</b></>}
          {" → "}<b>{p.new_name as string}</b>
        </span>
      );
    case "set_comment":
      return (
        <span>
          Comment on {p.addr ? <b>{p.addr as string}</b> : <b>{p.func as string}</b>}
          {": "}<i>{(p.comment as string)?.slice(0, 100)}</i>
        </span>
      );
    case "set_type":
      return (
        <span>
          Set type {p.addr ? <>at <b>{p.addr as string}</b></> : <><b>{p.func as string}</b>:<b>{p.var as string}</b></>}
          {" → "}<code>{p.type as string}</code>
        </span>
      );
    case "define_type":
      return <span>Define: <code>{(p.declare as string)?.slice(0, 120)}</code></span>;
    case "xrefs":
      return <span>Cross-references to <b>{p.addr as string}</b></span>;
    case "search":
      return <span>Search <code>{p.pattern as string}</code>{p.type ? ` in ${p.type}` : ""}</span>;
    case "search_bytes":
      return <span>Byte search <code>{p.pattern as string}</code></span>;
    case "execute_python":
      return (
        <div>
          <pre className="activity-code">{p.code as string}</pre>
          {ev.result_summary && <div style={{marginTop: 4}}>Result: <code>{ev.result_summary}</code></div>}
        </div>
      );
    case "get_comment":
      return <span>Get comment at {p.addr ? <b>{p.addr as string}</b> : <b>{p.func as string}</b>}</span>;
    case "examine":
      return <span>Examine <b>{p.addr as string}</b></span>;
    case "get_bytes":
      return <span>Read {p.size || 256} bytes at <b>{p.addr as string}</b></span>;
    case "get_type":
      return <span>Type detail: <b>{p.name as string}</b></span>;
    case "list_types":
      return <span>List types{p.kind ? ` (${p.kind})` : ""}{p.filter ? ` filter="${p.filter}"` : ""}</span>;
    case "open_database":
      return <span>Open <b>{p.path as string}</b></span>;
    case "survey":
      return <span>Binary survey</span>;
    default: {
      // Fallback: JSON dump
      const entries = Object.entries(p);
      if (entries.length === 0) return null;
      return <code className="activity-json">{JSON.stringify(p, null, 2)}</code>;
    }
  }
}

export function ActivityStream() {
  const { events, paused, setPaused } = useActivityStore();
  const topRef = useRef<HTMLDivElement>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!paused) {
      topRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [events.length, paused]);

  const handleNavigate = useCallback((ev: ActivityEvent, e: React.MouseEvent) => {
    e.stopPropagation();
    const target = extractTarget(ev);
    if (!target) return;
    const pid = ev.project_id || useProjectStore.getState().activeProjectId;
    if (pid) {
      if (pid !== useProjectStore.getState().activeProjectId) {
        useProjectStore.getState().setActiveProject(pid);
      }
      useViewStore.getState().navigateActive(pid, target);
    }
  }, []);

  const toggleExpand = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  return (
    <div className="panel activity-panel">
      <div className="panel-header">
        <span>Activity</span>
        <button
          className="panel-btn"
          onClick={() => setPaused(!paused)}
          title={paused ? "Resume auto-scroll" : "Pause auto-scroll"}
        >
          {paused ? "▶" : "⏸"}
        </button>
      </div>
      <div className="panel-body activity-list">
        {events.length === 0 && (
          <div className="empty-hint">Waiting for AI activity...</div>
        )}
        <div ref={topRef} />
        {[...events].reverse().map((ev) => {
          const target = extractTarget(ev);
          const isExpanded = expandedIds.has(ev.id);
          const hasDetail = ev.params && Object.keys(ev.params).length > 0;
          return (
            <div key={ev.id} className="activity-entry">
              <div
                className={`activity-item status-${ev.status} ${hasDetail ? "expandable" : ""}`}
                onClick={() => hasDetail && toggleExpand(ev.id)}
              >
                <span className="activity-status">{STATUS_ICON[ev.status] || "?"}</span>
                <span className="activity-time">{formatTime(ev.timestamp)}</span>
                <span
                  className="activity-kind"
                  style={{ color: KIND_COLORS[ev.kind] || "#aaa" }}
                >
                  {ev.tool_name}
                </span>
                <span className="activity-params">{ev.params_summary}</span>
                {ev.duration_ms != null && (
                  <span className="activity-duration">
                    {(ev.duration_ms / 1000).toFixed(1)}s
                  </span>
                )}
                {target && (
                  <button
                    className="activity-nav-btn"
                    onClick={(e) => handleNavigate(ev, e)}
                    title="Jump to"
                  >↗</button>
                )}
              </div>
              {isExpanded && (
                <div className="activity-detail">
                  {renderDetail(ev)}
                  {ev.result_summary && ev.tool_name !== "execute_python" && (
                    <div style={{marginTop: 4, color: "var(--text-muted)", fontSize: 11}}>
                      → {ev.result_summary}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
