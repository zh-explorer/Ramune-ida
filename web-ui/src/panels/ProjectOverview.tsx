import { useCallback, useEffect, useState } from "react";
import { useProjectStore } from "../stores/projectStore";
import { useViewStore } from "../stores/viewStore";
import { getProject, getProjectFiles, listFuncs } from "../api/client";
import type { ProjectDetail, ProjectFile } from "../api/types";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const OPENABLE_EXT = new Set([
  "", ".i64", ".idb", ".elf", ".exe", ".dll", ".so", ".dylib", ".bin", ".o",
]);

function isOpenable(name: string): boolean {
  const dot = name.lastIndexOf(".");
  if (dot < 0) return true; // no extension = likely a binary
  const ext = name.substring(dot).toLowerCase();
  return OPENABLE_EXT.has(ext);
}

async function openDatabase(pid: string, path: string): Promise<void> {
  const res = await fetch(`/api/projects/${pid}/open`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `HTTP ${res.status}`);
  }
}

async function closeDatabase(pid: string): Promise<void> {
  const res = await fetch(`/api/projects/${pid}/close`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `HTTP ${res.status}`);
  }
}

export function ProjectOverview() {
  const { activeProjectId, fetchProjects } = useProjectStore();
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [files, setFiles] = useState<ProjectFile[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [opening, setOpening] = useState<string | null>(null);
  const [closing, setClosing] = useState(false);

  const refresh = useCallback(() => {
    if (!activeProjectId) return;
    getProject(activeProjectId)
      .then(setDetail)
      .catch((e) => setError(String(e)));
    getProjectFiles(activeProjectId)
      .then((d) => setFiles(d.files))
      .catch(() => setFiles([]));
  }, [activeProjectId]);

  useEffect(() => {
    setDetail(null);
    setFiles([]);
    setError(null);
    refresh();
  }, [activeProjectId, refresh]);

  const handleOpen = useCallback(
    async (filename: string) => {
      if (!activeProjectId) return;
      setOpening(filename);
      setError(null);
      try {
        await openDatabase(activeProjectId, filename);
        refresh();
        fetchProjects();
        useProjectStore.getState().bumpDataVersion();
        // Auto-navigate to main/start
        try {
          const res = await listFuncs(activeProjectId);
          const funcs = ((res as any).items || []) as { addr: string; name: string }[];
          const target = funcs.find((f) => f.name === "main")
            || funcs.find((f) => f.name === "_start" || f.name === "start")
            || funcs[0];
          if (target) {
            useViewStore.getState().navigateActive(activeProjectId, target.addr);
          }
        } catch {}
      } catch (e) {
        setError(String(e));
      } finally {
        setOpening(null);
      }
    },
    [activeProjectId, refresh, fetchProjects],
  );

  const handleClose = useCallback(async () => {
    if (!activeProjectId) return;
    setClosing(true);
    setError(null);
    try {
      await closeDatabase(activeProjectId);
      refresh();
      fetchProjects();
    } catch (e) {
      setError(String(e));
    } finally {
      setClosing(false);
    }
  }, [activeProjectId, refresh, fetchProjects]);

  if (!activeProjectId) {
    return (
      <div className="panel">
        <div className="panel-header">Project</div>
        <div className="panel-body empty-hint">No project selected</div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header">Project: {activeProjectId}</div>
      <div className="panel-body">
        {error && <div className="error-msg">{error}</div>}
        {detail && (
          <div className="project-info">
            <div className="info-row">
              <span className="info-label">Database:</span>
              <span>{detail.exe_path || detail.idb_path || "—"}</span>
            </div>
            <div className="info-row">
              <span className="info-label">Worker:</span>
              <span className={detail.worker_alive ? "text-green" : "text-gray"}>
                {detail.worker_alive ? "Running" : "Stopped"}
              </span>
              {detail.worker_alive && (
                <button
                  className="btn-small btn-danger"
                  onClick={handleClose}
                  disabled={closing}
                >
                  {closing ? "Closing..." : "Close"}
                </button>
              )}
            </div>
            <div className="info-row">
              <span className="info-label">Active tasks:</span>
              <span>{detail.active_tasks.length}</span>
            </div>
          </div>
        )}
        {files.length > 0 && (
          <>
            <div className="section-title">Files</div>
            <div className="file-list">
              {files.map((f) => (
                <div key={f.name} className="file-item">
                  <a
                    className="file-name"
                    href={`/files/${activeProjectId}/${f.name}`}
                    download
                    title="Download"
                  >
                    {f.name}
                  </a>
                  <span className="file-actions">
                    {isOpenable(f.name) && (
                      <button
                        className="btn-small"
                        onClick={() => handleOpen(f.name)}
                        disabled={opening !== null}
                      >
                        {opening === f.name ? "Opening..." : "Open"}
                      </button>
                    )}
                    <span className="file-size">{formatSize(f.size)}</span>
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
