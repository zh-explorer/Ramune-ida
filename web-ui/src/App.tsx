import { useEffect, useRef, useCallback, useMemo } from "react";
import DockLayout from "rc-dock";
import type { LayoutData, TabData, TabGroup } from "rc-dock";
import "rc-dock/dist/rc-dock-dark.css";

import { Toolbar } from "./components/Toolbar";
import { StatusBar } from "./components/StatusBar";
import { ContextMenuLayer } from "./components/ContextMenu";
import { useGlobalShortcuts } from "./hooks/useGlobalShortcuts";
import { OverviewBar } from "./components/OverviewBar";
import { ActivityStream } from "./panels/ActivityStream";
import { ProjectOverview } from "./panels/ProjectOverview";
import { FunctionList } from "./panels/FunctionList";
import { StringList } from "./panels/StringList";
import { Decompile } from "./panels/Decompile";
import { Disassembly } from "./panels/Disassembly";
import { HexView } from "./panels/HexView";
import { LinearView } from "./panels/LinearView";
import { XrefsList } from "./panels/XrefsList";
import { ImportsList } from "./panels/ImportsList";
import { ExportsList } from "./panels/ExportsList";
import { NamesList } from "./panels/NamesList";
import { SegmentsList } from "./panels/SegmentsList";
import { LocalTypes } from "./panels/LocalTypes";
import { SearchPanel } from "./panels/SearchPanel";
import { useProjectStore } from "./stores/projectStore";
import { useViewStore } from "./stores/viewStore";
import {
  connectActivityStream,
  disconnectActivityStream,
  onDatabaseOpened,
} from "./stores/activityStore";
import { listFuncs } from "./api/client";
import { applyTheme, getStoredThemeId } from "./theme/themes";
import { TabTitle } from "./components/TabTitle";
import "./App.css";

// ── Panel type registry ─────────────────────────────────────────

const PANEL_TYPES: Record<string, { title: string; render: (tabId: string) => React.ReactElement }> = {
  functions:   { title: "Functions",    render: () => <FunctionList /> },
  strings:     { title: "Strings",      render: () => <StringList /> },
  hex:         { title: "Hex",          render: () => <HexView /> },
  project:     { title: "Project",      render: () => <ProjectOverview /> },
  decompile:   { title: "Decompile",    render: (id) => <Decompile tabId={id} /> },
  disassembly: { title: "Disassembly",  render: (id) => <Disassembly tabId={id} /> },
  idaview:     { title: "IDA View",     render: (id) => <LinearView tabId={id} /> },
  xrefs:       { title: "Xrefs",        render: () => <XrefsList /> },
  imports:     { title: "Imports",      render: () => <ImportsList /> },
  exports:     { title: "Exports",      render: () => <ExportsList /> },
  names:       { title: "Names",        render: () => <NamesList /> },
  segments:    { title: "Segments",     render: () => <SegmentsList /> },
  localtypes:  { title: "Local Types",  render: () => <LocalTypes /> },
  search:      { title: "Search",       render: () => <SearchPanel /> },
  activity:    { title: "Activity",     render: () => <ActivityStream /> },
};


function parseTabType(id: string): string {
  const colon = id.indexOf(":");
  return colon >= 0 ? id.substring(0, colon) : id;
}

let tabCounter = 100;

// Global panel opener — used by context menu / hooks to open panels programmatically
let _addPanel: ((type: string) => void) | null = null;
/** Open a panel of the given type. Callable from anywhere after App mounts. */
export function addPanel(type: string) { _addPanel?.(type); }

/**
 * Find the first existing tab of a given type, or null.
 * Used to check if e.g. an xrefs panel already exists.
 */
let _findTab: ((type: string) => string | null) | null = null;
export function findTabOfType(type: string): string | null { return _findTab?.(type) ?? null; }

function makeTab(id: string): TabData {
  const type = parseTabType(id);
  const reg = PANEL_TYPES[type];
  if (!reg) return { id, title: id, content: <div>Unknown: {id}</div>, group: "card" };
  return {
    id,
    title: <TabTitle tabId={id} />,
    content: <div style={{ height: "100%", overflow: "auto" }}>{reg.render(id)}</div>,
    closable: true,
    group: "card",
  };
}

function createNewTab(type: string): TabData {
  const id = `${type}:${++tabCounter}`;
  const tab = makeTab(id);
  // Assign independent channel for syncable panels
  if (["decompile", "disassembly", "idaview", "xrefs", "hex"].includes(type)) {
    const store = useViewStore.getState();
    const used = new Set(Object.values(store.tabChannels));
    const free = ["B", "C", "D", "E"].find((ch) => !used.has(ch)) || "E";
    store.setTabChannel(id, free);
  }
  return tab;
}

function loadTab(data: TabData): TabData {
  const id = data.id!;
  const type = parseTabType(id);
  const reg = PANEL_TYPES[type];
  if (!reg) return { ...data, content: <div>Unknown: {id}</div> };
  return {
    ...data,
    title: <TabTitle tabId={id} />,
    content: <div style={{ height: "100%", overflow: "auto" }}>{reg.render(id)}</div>,
    closable: true,
    group: "card",
  };
}

// ── Layout ──────────────────────────────────────────────────────

const groups: Record<string, TabGroup> = {
  card: {
    floatable: true,
    maximizable: true,
    animated: false,
  },
};

const LS_KEY = "ramune-web:dock-layout-v3";

function createDefaultLayout(): LayoutData {
  const store = useViewStore.getState();
  store.setTabChannel("decompile", "A");
  store.setTabChannel("idaview", "A");
  store.setTabChannel("disassembly", "A");
  store.setTabChannel("hex", "A");

  return {
    dockbox: {
      mode: "horizontal",
      children: [
        {
          // Left: Functions/Strings on top, Project on bottom
          mode: "vertical",
          size: 250,
          children: [
            {
              size: 400,
              tabs: [makeTab("functions"), makeTab("strings")],
            },
            {
              size: 300,
              tabs: [makeTab("project")],
            },
          ],
        },
        {
          // Center: Decompile on top, Activity on bottom
          mode: "vertical",
          size: 500,
          children: [
            { size: 500, tabs: [makeTab("decompile")] },
            { size: 200, tabs: [makeTab("activity")] },
          ],
        },
        {
          // Right: IDA View/Disassembly on top, Hex on bottom
          mode: "vertical",
          size: 500,
          children: [
            { size: 500, tabs: [makeTab("idaview"), makeTab("disassembly")] },
            { size: 200, tabs: [makeTab("hex")] },
          ],
        },
      ],
    },
  };
}

function loadSavedLayout(): LayoutData | null {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed?.dockbox) return parsed;
  } catch {}
  localStorage.removeItem(LS_KEY);
  return null;
}

// ── App ─────────────────────────────────────────────────────────

function App() {
  const { fetchProjects, fetchSystem, activeProjectId } = useProjectStore();
  const clearView = useViewStore((s) => s.clearAll);
  const dockRef = useRef<DockLayout>(null);

  useGlobalShortcuts();

  // Compute initial layout ONCE
  const initialLayout = useMemo(() => loadSavedLayout() || createDefaultLayout(), []);

  // Apply saved theme on mount
  useEffect(() => {
    applyTheme(getStoredThemeId());
  }, []);

  useEffect(() => { clearView(); }, [activeProjectId, clearView]);

  useEffect(() => {
    if (activeProjectId) {
      localStorage.setItem("ramune-web:active-project", activeProjectId);
    }
  }, [activeProjectId]);

  useEffect(() => {
    const saved = localStorage.getItem("ramune-web:active-project");
    if (saved) {
      useProjectStore.getState().setActiveProject(saved);
      // Restore last viewed functions after a short delay (let projects load first)
      setTimeout(() => {
        const pid = useProjectStore.getState().activeProjectId;
        if (pid) useViewStore.getState().restoreSession(pid);
      }, 500);
    }

    fetchProjects();
    fetchSystem();
    connectActivityStream();

    // Navigate to a default function when a project becomes ready
    async function autoNavigate(projectId: string) {
      fetchProjects();
      const ps = useProjectStore.getState();
      if (!ps.activeProjectId) ps.setActiveProject(projectId);
      try {
        const res = await listFuncs(projectId);
        const funcs = ((res as any).items || []) as { addr: string; name: string }[];
        const main = funcs.find((f) => f.name === "main");
        const start = funcs.find((f) => f.name === "_start" || f.name === "start");
        const target = main || start || funcs[0];
        if (target) {
          useViewStore.getState().navigateActive(projectId, target.addr);
        }
      } catch {}
    }

    // When a database is opened (via MCP or manual), refresh and navigate
    const unsubDb = onDatabaseOpened((projectId) => {
      useProjectStore.getState().bumpDataVersion();
      setTimeout(() => autoNavigate(projectId), 300);
    });

    // On first load: if active project already has a database, auto-navigate
    setTimeout(() => {
      const ps = useProjectStore.getState();
      const vs = useViewStore.getState();
      const pid = ps.activeProjectId;
      if (pid && !vs.getChannel(vs.activeChannel).currentFunc) {
        const proj = ps.projects.find((p) => p.project_id === pid);
        if (proj?.has_database) autoNavigate(pid);
      }
    }, 1000);

    // When active project changes, auto-navigate if it has a database
    const unsubProject = useProjectStore.subscribe((state, prev) => {
      if (state.activeProjectId && state.activeProjectId !== (prev as any).activeProjectId) {
        const proj = state.projects.find((p) => p.project_id === state.activeProjectId);
        if (proj?.has_database) {
          setTimeout(() => autoNavigate(state.activeProjectId!), 200);
        }
      }
    });

    const interval = setInterval(() => {
      fetchProjects();
      fetchSystem();
    }, 5000);

    return () => {
      clearInterval(interval);
      disconnectActivityStream();
      unsubDb();
      unsubProject();
    };
  }, [fetchProjects, fetchSystem]);

  const onLayoutChange = useCallback((newLayout: LayoutData) => {
    try {
      const layout = dockRef.current?.saveLayout();
      if (layout) localStorage.setItem(LS_KEY, JSON.stringify(layout));
    } catch {}

    // Clean up tabChannels for tabs that no longer exist in the layout
    const store = useViewStore.getState();
    const existingIds = new Set<string>();
    function collectIds(box: any) {
      if (box?.tabs) {
        for (const tab of box.tabs) {
          if (tab.id) existingIds.add(tab.id);
        }
      }
      if (box?.children) {
        for (const child of box.children) collectIds(child);
      }
    }
    collectIds(newLayout.dockbox);
    collectIds(newLayout.floatbox);

    for (const tabId of Object.keys(store.tabChannels)) {
      if (!existingIds.has(tabId)) {
        store.removeTab(tabId);
      }
    }
  }, []);

  const handleAddPanel = useCallback((type: string) => {
    if (!dockRef.current) return;
    dockRef.current.dockMove(createNewTab(type), null, "float");
  }, []);

  // Register global panel opener
  useEffect(() => {
    _addPanel = handleAddPanel;
    _findTab = (type: string) => {
      const store = useViewStore.getState();
      for (const tabId of Object.keys(store.tabChannels)) {
        if (parseTabType(tabId) === type) return tabId;
      }
      return null;
    };
    return () => { _addPanel = null; _findTab = null; };
  }, [handleAddPanel]);

  const handleResetLayout = useCallback(() => {
    localStorage.removeItem(LS_KEY);
    window.location.reload();
  }, []);

  return (
    <div className="app-root">
      <Toolbar
        onAddPanel={handleAddPanel}
        onResetLayout={handleResetLayout}
      />
      <div className="overview-bar-wrap"><OverviewBar /></div>
      <div className="app-main">
        <DockLayout
          ref={dockRef}
          defaultLayout={initialLayout}
          loadTab={loadTab}
          groups={groups}
          onLayoutChange={onLayoutChange}
          style={{ position: "absolute", left: 0, top: 0, right: 0, bottom: 0 }}
        />
      </div>
      <StatusBar />
      <ContextMenuLayer />
    </div>
  );
}

export default App;
