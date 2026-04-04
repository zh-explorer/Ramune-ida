import { create } from "zustand";
import { funcView } from "../api/client";
import type { FuncViewData } from "../api/types";

// ── Channel state ───────────────────────────────────────────────

export interface ChannelState {
  currentFunc: string | null;
  funcName: string | null;
  funcData: FuncViewData | null;
  loading: boolean;
  error: string | null;
  highlightDecompileLines: number[];
  highlightDisasmAddrs: string[];
  highlightToken: string | null;
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
  highlightFromDecompile: (ch: string, lineIdx: number) => void;
  highlightFromDisasm: (ch: string, addr: string) => void;
  setHighlightToken: (ch: string, token: string | null) => void;
  clearHighlight: (ch: string) => void;
  clear: (ch: string) => void;
  clearAll: () => void;
}

export const useViewStore = create<ViewStore>((set, get) => ({
  channels: { A: emptyChannel() },
  activeChannel: "A",
  tabChannels: {},

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

  navigateTo: (ch: string, projectId: string, func: string) => {
    const state = get();
    const channel = state.channels[ch] || emptyChannel();

    const newHistory = channel.history.slice(0, channel.historyIndex + 1);
    newHistory.push(func);

    const updated: ChannelState = {
      ...channel,
      currentFunc: func,
      funcName: null,
      funcData: null,
      loading: true,
      error: null,
      highlightDecompileLines: [],
      highlightDisasmAddrs: [],
      history: newHistory,
      historyIndex: newHistory.length - 1,
    };

    set((s) => ({
      channels: { ...s.channels, [ch]: updated },
      activeChannel: ch,
    }));

    const cacheKey = `${projectId}:${func}`;
    const cached = channel._cache.get(cacheKey);
    if (cached) {
      set((s) => ({
        channels: {
          ...s.channels,
          [ch]: { ...s.channels[ch], funcData: cached, funcName: cached.func.name, loading: false },
        },
      }));
      return;
    }

    funcView(projectId, func)
      .then((data) => {
        const cache = get().channels[ch]?._cache || new Map();
        if (cache.size > 30) {
          const first = cache.keys().next().value;
          if (first) cache.delete(first);
        }
        cache.set(cacheKey, data);
        set((s) => ({
          channels: {
            ...s.channels,
            [ch]: {
              ...s.channels[ch],
              funcData: data,
              funcName: data.func.name,
              loading: false,
              _cache: cache,
            },
          },
        }));
      })
      .catch((e: any) => {
        const msg = e?.message || String(e);
        set((s) => ({
          channels: {
            ...s.channels,
            [ch]: { ...s.channels[ch], funcData: null, loading: false, error: msg },
          },
        }));
      });
  },

  navigateActive: (projectId: string, func: string) => {
    get().navigateTo(get().activeChannel, projectId, func);
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
}));
