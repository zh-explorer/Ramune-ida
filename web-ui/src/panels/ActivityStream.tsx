import { useCallback, useEffect, useRef } from "react";
import { useActivityStore } from "../stores/activityStore";
import { useProjectStore } from "../stores/projectStore";
import { useViewStore } from "../stores/viewStore";
import type { ActivityEvent } from "../api/types";

const KIND_COLORS: Record<string, string> = {
  read: "#4fc3f7",
  write: "#ffb74d",
  unsafe: "#ef5350",
};

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString("en-US", { hour12: false });
}

/** Extract a navigable target (address or symbol) from activity event. */
function extractTarget(ev: ActivityEvent): string | null {
  // Match common param names that contain addresses or symbols
  const paramMatch = ev.params_summary.match(
    /(?:func|addr|name|target|var)=([^\s,]+)/,
  );
  if (paramMatch) return paramMatch[1];
  // Match bare hex address anywhere in summary
  const hexMatch = ev.params_summary.match(/\b(0x[0-9a-fA-F]+)\b/);
  if (hexMatch) return hexMatch[1];
  return null;
}

export function ActivityStream() {
  const { events, paused, setPaused } = useActivityStore();
  const topRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!paused) {
      topRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [events.length, paused]);

  const handleClick = useCallback((ev: ActivityEvent) => {
    const target = extractTarget(ev);
    if (!target) return;
    const pid = ev.project_id || useProjectStore.getState().activeProjectId;
    if (pid) {
      // Switch project if different
      if (pid !== useProjectStore.getState().activeProjectId) {
        useProjectStore.getState().setActiveProject(pid);
      }
      useViewStore.getState().navigateActive(pid, target);
    }
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
          return (
            <div
              key={ev.id}
              className={`activity-item status-${ev.status} ${target ? "clickable" : ""}`}
              onClick={target ? () => handleClick(ev) : undefined}
            >
              <span className="activity-time">{formatTime(ev.timestamp)}</span>
              <span
                className="activity-kind"
                style={{ color: KIND_COLORS[ev.kind] || "#aaa" }}
              >
                {ev.tool_name}
              </span>
              <span className="activity-params">
                {ev.params_summary}
              </span>
              {ev.duration_ms != null && (
                <span className="activity-duration">
                  {(ev.duration_ms / 1000).toFixed(1)}s
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
