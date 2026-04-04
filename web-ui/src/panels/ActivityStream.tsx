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

/** Extract a navigable target from activity params (func=main, addr=0x1234) */
function extractTarget(ev: ActivityEvent): string | null {
  const match = ev.params_summary.match(
    /(?:func|addr)=([^\s,]+)/,
  );
  return match ? match[1] : null;
}

export function ActivityStream() {
  const { events, paused, setPaused } = useActivityStore();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!paused) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
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
        {events.map((ev) => {
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
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
