import { useCallback, useEffect, useState } from "react";
import { survey } from "../api/client";
import { useProjectStore } from "../stores/projectStore";
import { useViewStore } from "../stores/viewStore";

interface SegmentEntry {
  name: string;
  start: string;
  end: string;
  perm: string;
}

function formatSize(start: string, end: string): string {
  const s = parseInt(start, 16);
  const e = parseInt(end, 16);
  const size = e - s;
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export function SegmentsList() {
  const { activeProjectId } = useProjectStore();
  const navigateActive = useViewStore((s) => s.navigateActive);
  const [segments, setSegments] = useState<SegmentEntry[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchData = useCallback((initial = false) => {
    if (!activeProjectId) return;
    if (initial) setLoading(true);
    survey(activeProjectId)
      .then((res: any) => setSegments(res.segments || []))
      .catch(() => { if (initial) setSegments([]); })
      .finally(() => setLoading(false));
  }, [activeProjectId]);

  useEffect(() => {
    if (!activeProjectId) { setSegments([]); return; }
    fetchData(true);
  }, [activeProjectId, fetchData]);

  const handleClick = useCallback(
    (seg: SegmentEntry) => {
      if (activeProjectId) navigateActive(activeProjectId, seg.start);
    },
    [activeProjectId, navigateActive],
  );

  return (
    <div className="panel" onFocus={() => fetchData()} tabIndex={-1}>
      <div className="panel-header">
        <span>Segments ({segments.length})</span>
      </div>
      <div className="panel-body">
        {loading && <div className="empty-hint">Loading...</div>}
        {!loading && segments.length === 0 && <div className="empty-hint">No segments</div>}
        {!loading && segments.length > 0 && (
          <table className="segments-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Start</th>
                <th>End</th>
                <th>Size</th>
                <th>Perm</th>
              </tr>
            </thead>
            <tbody>
              {segments.map((seg, i) => (
                <tr key={i} className="segment-row" onClick={() => handleClick(seg)}>
                  <td className="seg-name">{seg.name}</td>
                  <td className="seg-addr">{seg.start}</td>
                  <td className="seg-addr">{seg.end}</td>
                  <td className="seg-size">{formatSize(seg.start, seg.end)}</td>
                  <td className="seg-perm">{seg.perm}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
