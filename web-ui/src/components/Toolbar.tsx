import { useProjectStore } from "../stores/projectStore";
import { MenuBar } from "./MenuBar";

interface ToolbarProps {
  onAddPanel: (type: string) => void;
  onResetLayout: () => void;
}

export function Toolbar({ onAddPanel, onResetLayout }: ToolbarProps) {
  const { projects, activeProjectId, setActiveProject } = useProjectStore();

  return (
    <div className="toolbar">
      <span className="toolbar-title">Ramune-ida</span>
      <MenuBar
        onAddPanel={onAddPanel}
        onResetLayout={onResetLayout}
      />
      <div className="toolbar-spacer" />
      <select
        className="project-selector"
        value={activeProjectId || ""}
        onChange={(e) => setActiveProject(e.target.value || null)}
      >
        {projects.length === 0 && <option value="">No projects</option>}
        {projects.map((p) => (
          <option key={p.project_id} value={p.project_id}>
            {p.exe_path || p.idb_path || p.project_id}
            {p.worker_alive ? " ●" : ""}
          </option>
        ))}
      </select>
    </div>
  );
}
