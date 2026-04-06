import { create } from "zustand";
import { funcView, resolveTarget } from "../api/client";
import type { FuncViewData, ResolveResult } from "../api/types";

// ── Channel state ───────────────────────────────────────────────

export interface ChannelState {
  // Current function view
  currentFunc: string | null;
  funcName: string | null;
  funcData: FuncViewData | null;
  loading: boolean;
  error: string | null;

  // Current target address (for IDA View / Hex View to follow)
  targetAddr: string | null;

  // Last resolve result
  lastResolve: ResolveResult | null;

  // Sync highlights
  highlightDecompileLines: number[];
  highlightDisasmAddrs: string[];
  highlightToken: string | null;

  // Navigation history
  history: string[];
  historyIndex: number;
  _cache: Map<string, FuncViewData>;
}

function emptyChannel(): ChannelState {
  return {
    currentFunc: null,
    funcName: null,
    funcData: null,
    loading: false,
    error: null,
    targetAddr: null,
    lastResolve: null,
    highlightDecompileLines: [],
    highlightDisasmAddrs: [],
    highlightToken: null,
    history: [],
    historyIndex: -1,
    _cache: new Map(),
  };
}

// ── Store ───────────────────────────────────────────────────────

interface ViewStore {
  // Multi-channel state
  channels: Record<string, ChannelState>;
  activeChannel: string;

  // Tab → channel mapping
  tabChannels: Record<string, string>; // tabId → channelId
  // Tab → channel mapping
  // Actions
  getChannel: (ch: string) => ChannelState;
  setActiveChannel: (ch: string) => void;
  setTabChannel: (tabId: string, ch: string) => void;
  getTabChannel: (tabId: string) => string;
  removeTab: (tabId: string) => void;

  navigateTo: (ch: string, projectId: string, func: string) => void;
  navigateActive: (projectId: string, func: string) => void;
  goBack: (ch: string, projectId: string) => void;
  goForward: (ch: string, projectId: string) => void;
  canGoBack: (ch: string) => boolean;
  canGoForward: (ch: string) => boolean;
  highlightFromDecompile: (ch: string, lineIdx: number) => void;
  highlightFromDisasm: (ch: string, addr: string) => void;
  setTargetAddr: (ch: string, addr: string) => void;
  setHighlightToken: (ch: string, token: string | null) => void;
  clearHighlight: (ch: string) => void;
  clear: (ch: string) => void;
  saveSession: () => void;
  restoreSession: (projectId: string) => void;
  clearAll: () => void;
  invalidateCache: () => void;

  // Xrefs request signal (from context menu → XrefsList)
  xrefRequest: { target: string; ts: number } | null;
  requestXrefs: (ch: string, target: string) => void;
}

export const useViewStore = create<ViewStore>((set, get) => ({
  channels: { A: emptyChannel() },
  activeChannel: "A",
  tabChannels: {},
  xrefRequest: null,

  getChannel: (ch: string) => {
    return get().channels[ch] || emptyChannel();
  },

  setActiveChannel: (ch: string) => {
    set({ activeChannel: ch });
  },

  setTabChannel: (tabId: string, ch: string) => {
    set((s) => ({
      tabChannels: { ...s.tabChannels, [tabId]: ch },
    }));
    // Ensure channel exists
    if (!get().channels[ch]) {
      set((s) => ({
        channels: { ...s.channels, [ch]: emptyChannel() },
      }));
    }
  },

  getTabChannel: (tabId: string) => {
    return get().tabChannels[tabId] || "A";
  },

  removeTab: (tabId: string) => {
    set((s) => {
      const { [tabId]: _, ...rest } = s.tabChannels;
      return { tabChannels: rest };
    });
  },

  navigateTo: (ch: string, projectId: string, target: string) => {
    const state = get();
    const channel = state.channels[ch] || emptyChannel();

    // Update history
    const newHistory = channel.history.slice(0, channel.historyIndex + 1);
    newHistory.push(target);

    set((s) => ({
      channels: {
        ...s.channels,
        [ch]: {
          ...channel,
          loading: true,
          error: null,
          highlightDecompileLines: [],
          highlightDisasmAddrs: [],
          history: newHistory,
          historyIndex: newHistory.length - 1,
        },
      },
      activeChannel: ch,
    }));

    const update = (patch: Partial<ChannelState>) => {
      set((s) => ({
        channels: {
          ...s.channels,
          [ch]: { ...s.channels[ch], ...patch },
        },
      }));
      // Auto-save session when function changes
      if (patch.currentFunc !== undefined || patch.funcData !== undefined) {
        setTimeout(() => get().saveSession(), 0);
      }
    };

    // Step 1: resolve the target
    resolveTarget(projectId, target)
      .then((resolved) => {
        update({ lastResolve: resolved, targetAddr: resolved.addr || null });

        // Step 2: decide what to do based on type
        const funcAddr = resolved.type === "function"
          ? resolved.addr
          : resolved.func_addr;

        if (!funcAddr) {
          // Not in a function (data, string, unknown) → just set targetAddr, done
          update({ currentFunc: null, funcData: null, funcName: null, loading: false });
          return;
        }

        // Check if we already have this function loaded
        const current = get().channels[ch];
        if (current?.funcData?.func?.addr === funcAddr) {
          // Same function — just update highlight, skip func_view
          update({
            loading: false,
            highlightDisasmAddrs: resolved.type !== "function" && resolved.addr ? [resolved.addr] : [],
          });
          return;
        }

        // Check cache
        const cacheKey = `${projectId}:${funcAddr}`;
        const cached = channel._cache.get(cacheKey);
        if (cached) {
          update({
            currentFunc: funcAddr,
            funcData: cached,
            funcName: cached.func.name,
            loading: false,
            highlightDisasmAddrs: resolved.type !== "function" && resolved.addr ? [resolved.addr] : [],
          });
          return;
        }

        // Load func_view — if it fails, we still have targetAddr for IDA View
        funcView(projectId, funcAddr)
          .then((data) => {
            const cache = get().channels[ch]?._cache || new Map();
            if (cache.size > 30) {
              const first = cache.keys().next().value;
              if (first) cache.delete(first);
            }
            cache.set(cacheKey, data);
            update({
              currentFunc: funcAddr,
              funcData: data,
              funcName: data.func.name,
              loading: false,
              _cache: cache,
              highlightDisasmAddrs: resolved.type !== "function" && resolved.addr ? [resolved.addr] : [],
            });
          })
          .catch((e: any) => {
            // Decompile failed — not fatal, IDA View already jumped via targetAddr
            update({
              currentFunc: funcAddr,
              funcData: null,
              funcName: resolved.name || null,
              loading: false,
              error: e?.message || String(e),
            });
          });
      })
      .catch((e: any) => {
        update({
          loading: false,
          error: e?.message || String(e),
        });
      });
  },

  navigateActive: (projectId: string, func: string) => {
    get().navigateTo(get().activeChannel, projectId, func);
  },

  goBack: (ch: string, projectId: string) => {
    const channel = get().channels[ch];
    if (!channel || channel.historyIndex <= 0) return;
    const newIndex = channel.historyIndex - 1;
    const target = channel.history[newIndex];
    // Set index without pushing to history
    set((s) => ({
      channels: {
        ...s.channels,
        [ch]: { ...s.channels[ch], historyIndex: newIndex },
      },
    }));
    // Navigate without adding to history (call resolve + load directly)
    get().navigateTo(ch, projectId, target);
    // Fix: navigateTo pushes to history, so undo that
    set((s) => {
      const c = s.channels[ch];
      if (!c) return s;
      return {
        channels: {
          ...s.channels,
          [ch]: {
            ...c,
            history: channel.history, // restore original history
            historyIndex: newIndex,
          },
        },
      };
    });
  },

  goForward: (ch: string, projectId: string) => {
    const channel = get().channels[ch];
    if (!channel || channel.historyIndex >= channel.history.length - 1) return;
    const newIndex = channel.historyIndex + 1;
    const target = channel.history[newIndex];
    set((s) => ({
      channels: {
        ...s.channels,
        [ch]: { ...s.channels[ch], historyIndex: newIndex },
      },
    }));
    get().navigateTo(ch, projectId, target);
    set((s) => {
      const c = s.channels[ch];
      if (!c) return s;
      return {
        channels: {
          ...s.channels,
          [ch]: {
            ...c,
            history: channel.history,
            historyIndex: newIndex,
          },
        },
      };
    });
  },

  canGoBack: (ch: string) => {
    const channel = get().channels[ch];
    return !!channel && channel.historyIndex > 0;
  },

  canGoForward: (ch: string) => {
    const channel = get().channels[ch];
    return !!channel && channel.historyIndex < channel.history.length - 1;
  },

  setTargetAddr: (ch: string, addr: string) => {
    set((s) => ({
      channels: {
        ...s.channels,
        [ch]: {
          ...s.channels[ch],
          highlightDisasmAddrs: [addr],
          targetAddr: addr,
        },
      },
    }));
  },

  highlightFromDecompile: (ch: string, lineIdx: number) => {
    const data = get().channels[ch]?.funcData;
    if (!data) return;

    const line = data.decompile[lineIdx];
    if (!line) return;

    const addrs = line.addrs;
    const allLines = new Set<number>([lineIdx]);
    for (const addr of addrs) {
      for (const dl of data.disasm) {
        if (dl.addr === addr) {
          for (const ln of dl.decompile_lines) allLines.add(ln);
        }
      }
    }

    set((s) => ({
      channels: {
        ...s.channels,
        [ch]: {
          ...s.channels[ch],
          highlightDecompileLines: Array.from(allLines).sort((a, b) => a - b),
          highlightDisasmAddrs: addrs,
        },
      },
    }));
  },

  highlightFromDisasm: (ch: string, addr: string) => {
    const data = get().channels[ch]?.funcData;
    if (!data) return;

    const insn = data.disasm.find((d) => d.addr === addr);
    if (!insn) return;

    const lines = insn.decompile_lines;
    const allAddrs = new Set<string>([addr]);
    for (const lineIdx of lines) {
      const dcLine = data.decompile[lineIdx];
      if (dcLine) {
        for (const a of dcLine.addrs) allAddrs.add(a);
      }
    }

    set((s) => ({
      channels: {
        ...s.channels,
        [ch]: {
          ...s.channels[ch],
          highlightDecompileLines: lines,
          highlightDisasmAddrs: Array.from(allAddrs),
        },
      },
    }));
  },

  setHighlightToken: (ch: string, token: string | null) => {
    set((s) => ({
      channels: {
        ...s.channels,
        [ch]: { ...s.channels[ch], highlightToken: token },
      },
    }));
  },

  clearHighlight: (ch: string) => {
    set((s) => ({
      channels: {
        ...s.channels,
        [ch]: {
          ...s.channels[ch],
          highlightDecompileLines: [],
          highlightDisasmAddrs: [],
          highlightToken: null,
        },
      },
    }));
  },

  clear: (ch: string) => {
    set((s) => ({
      channels: {
        ...s.channels,
        [ch]: emptyChannel(),
      },
    }));
  },

  clearAll: () => {
    set({ channels: { A: emptyChannel() }, activeChannel: "A" });
  },

  saveSession: () => {
    const state = get();
    const session: Record<string, string | null> = {};
    for (const [ch, channelState] of Object.entries(state.channels)) {
      if (channelState.currentFunc) {
        session[ch] = channelState.currentFunc;
      }
    }
    try {
      localStorage.setItem("ramune-web:session", JSON.stringify({
        channels: session,
        activeChannel: state.activeChannel,
        tabChannels: state.tabChannels,
      }));
    } catch {}
  },

  restoreSession: (projectId: string) => {
    try {
      const raw = localStorage.getItem("ramune-web:session");
      if (!raw) return;
      const saved = JSON.parse(raw);

      // Restore tab channels
      if (saved.tabChannels) {
        set({ tabChannels: saved.tabChannels });
      }
      if (saved.activeChannel) {
        set({ activeChannel: saved.activeChannel });
      }

      // Re-navigate each channel to its last function
      if (saved.channels) {
        for (const [ch, func] of Object.entries(saved.channels)) {
          if (func && typeof func === "string") {
            get().navigateTo(ch, projectId, func);
          }
        }
      }
    } catch {}
  },

  invalidateCache: () => {
    const state = get();
    const updated: Record<string, ChannelState> = {};
    for (const [ch, channel] of Object.entries(state.channels)) {
      updated[ch] = { ...channel, _cache: new Map() };
    }
    set({ channels: updated });
    // Re-navigate current function on active channel to refresh
    const active = state.channels[state.activeChannel];
    if (active?.currentFunc) {
      // Slight delay to let cache clear propagate
      setTimeout(() => {
        const s = get();
        const ch = s.activeChannel;
        const pid = active.currentFunc;
        if (pid) {
          // Force reload by navigating to same function
          const { useProjectStore } = require("./projectStore");
          const projectId = useProjectStore.getState().activeProjectId;
          if (projectId) s.navigateTo(ch, projectId, active.currentFunc!);
        }
      }, 50);
    }
  },

  requestXrefs: (_ch: string, target: string) => {
    set({ xrefRequest: { target, ts: Date.now() } });
  },
}));
