import { create } from "zustand";
import type { ActivityEvent } from "../api/types";

interface ActivityState {
  events: ActivityEvent[];
  connected: boolean;
  paused: boolean;

  addEvent: (event: ActivityEvent) => void;
  setPaused: (paused: boolean) => void;
  setConnected: (connected: boolean) => void;
  clear: () => void;
}

export const useActivityStore = create<ActivityState>((set) => ({
  events: [],
  connected: false,
  paused: false,

  addEvent: (event) =>
    set((state) => {
      // Update existing event (same id) or append
      const idx = state.events.findIndex((e) => e.id === event.id);
      if (idx >= 0) {
        const updated = [...state.events];
        updated[idx] = event;
        return { events: updated };
      }
      // Keep last 500 events
      const events = [...state.events, event];
      if (events.length > 500) events.splice(0, events.length - 500);
      return { events };
    }),

  setPaused: (paused) => set({ paused }),
  setConnected: (connected) => set({ connected }),
  clear: () => set({ events: [] }),
}));

// Callbacks for database open events
const _dbOpenCallbacks: Array<(projectId: string) => void> = [];
export function onDatabaseOpened(cb: (projectId: string) => void) {
  _dbOpenCallbacks.push(cb);
  return () => { const i = _dbOpenCallbacks.indexOf(cb); if (i >= 0) _dbOpenCallbacks.splice(i, 1); };
}

// WebSocket connection manager
let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

export function connectActivityStream() {
  if (ws?.readyState === WebSocket.OPEN) return;

  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${proto}//${window.location.host}/ws/activity`;

  ws = new WebSocket(url);

  ws.onopen = () => {
    useActivityStore.getState().setConnected(true);
  };

  ws.onmessage = (msg) => {
    try {
      const event: ActivityEvent = JSON.parse(msg.data);
      useActivityStore.getState().addEvent(event);
      // Detect open_database completion
      if (
        event.tool_name === "open_database" &&
        event.status === "completed" &&
        event.project_id
      ) {
        for (const cb of _dbOpenCallbacks) cb(event.project_id);
      }
      // Refresh decompile cache on write operations (rename, set_comment, etc.)
      // Only invalidate func cache — don't refresh all list panels to avoid
      // flooding the worker queue with serial requests
      if (
        event.status === "completed" &&
        event.kind === "write" &&
        event.project_id
      ) {
        const { useViewStore } = require("./viewStore");
        useViewStore.getState().invalidateCache();
      }
    } catch {
      // ignore malformed
    }
  };

  ws.onclose = () => {
    useActivityStore.getState().setConnected(false);
    ws = null;
    // Auto-reconnect after 3s
    reconnectTimer = setTimeout(connectActivityStream, 3000);
  };

  ws.onerror = () => {
    ws?.close();
  };
}

export function disconnectActivityStream() {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  ws?.close();
  ws = null;
}
