import { useCallback, useEffect, useRef, useState } from "react";
import { useProjectStore } from "../stores/projectStore";
import { useViewStore } from "../stores/viewStore";

interface Region { start: string; end: string; type: string; }
interface Segment { start: string; end: string; name: string; }
interface OverviewData { min_ea: string; max_ea: string; segments: Segment[]; regions: Region[]; }

const COLORS: Record<string, string> = { code: "#569cd6", data: "#dcdcaa", unknown: "#505050" };
const BG = "#000000";
const CURSOR = "#ffffff";
const BAR_H = 20;
const GAP_PX = 4;        // fixed gap width between segments
const TAIL_RATIO = 0.05;  // 5% trailing black
const ZOOM_FACTOR = 0.15;
const THROTTLE_MS = 100;

function hex(s: string): number { return parseInt(s, 16) || 0; }

/** Segment pixel layout entry */
interface SegPx { addrStart: number; addrEnd: number; pxStart: number; pxEnd: number; }

/** Build pixel layout: segments get proportional space, gaps get fixed px, tail gets 20%. */
function buildLayout(segments: Segment[], totalPx: number): SegPx[] {
  if (!segments.length || totalPx <= 0) return [];
  const totalData = segments.reduce((s, seg) => s + hex(seg.end) - hex(seg.start), 0);
  if (totalData <= 0) return [];

  const gapTotal = (segments.length - 1) * GAP_PX;
  const tailPx = Math.round(totalPx * TAIL_RATIO);
  const dataPx = Math.max(1, totalPx - gapTotal - tailPx);

  const layout: SegPx[] = [];
  let px = 0;
  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i];
    const aStart = hex(seg.start);
    const aEnd = hex(seg.end);
    const segSize = aEnd - aStart;
    const segPx = Math.round((segSize / totalData) * dataPx);
    layout.push({ addrStart: aStart, addrEnd: aEnd, pxStart: px, pxEnd: px + segPx });
    px += segPx;
    if (i < segments.length - 1) px += GAP_PX;
  }
  return layout;
}

/** Pixel → address. Returns null if in gap or tail. */
function pxToAddr(px: number, layout: SegPx[]): number | null {
  for (const seg of layout) {
    if (px >= seg.pxStart && px < seg.pxEnd) {
      const ratio = (px - seg.pxStart) / Math.max(1, seg.pxEnd - seg.pxStart);
      return Math.floor(seg.addrStart + ratio * (seg.addrEnd - seg.addrStart));
    }
  }
  return null;
}

/** Address → pixel. Returns null if outside all segments. */
function addrToPx(addr: number, layout: SegPx[]): number | null {
  for (const seg of layout) {
    if (addr >= seg.addrStart && addr < seg.addrEnd) {
      const ratio = (addr - seg.addrStart) / Math.max(1, seg.addrEnd - seg.addrStart);
      return seg.pxStart + ratio * (seg.pxEnd - seg.pxStart);
    }
  }
  return null;
}

/** Build a pixel color buffer from regions + layout. */
function buildColorBuf(regions: Region[], layout: SegPx[], width: number): Uint8Array {
  // 0=bg, 1=code, 2=data, 3=unknown
  const buf = new Uint8Array(width); // all 0 = bg/gap
  for (const region of regions) {
    const rStart = hex(region.start);
    const rEnd = hex(region.end);
    const px0 = addrToPx(rStart, layout);
    const px1 = addrToPx(rEnd - 1, layout);
    if (px0 === null || px1 === null) continue;
    const ipx0 = Math.max(0, Math.floor(px0));
    const ipx1 = Math.min(width - 1, Math.ceil(px1));
    const val = region.type === "code" ? 1 : region.type === "data" ? 2 : 3;
    for (let x = ipx0; x <= ipx1; x++) buf[x] = val;
  }
  return buf;
}

const COLOR_MAP = [BG, COLORS.code, COLORS.data, COLORS.unknown];

export function OverviewBar() {
  const { activeProjectId } = useProjectStore();
  const store = useViewStore();
  const ch = store.activeChannel;
  const channel = store.getChannel(ch);
  const currentAddr = channel.targetAddr || channel.currentFunc;

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [data, setData] = useState<OverviewData | null>(null);

  // Virtual width (CSS px). >= container width. Grows with zoom.
  const virtualWidthRef = useRef(0);
  const scrollOffsetRef = useRef(0); // scroll offset in CSS px
  const layoutRef = useRef<SegPx[]>([]);
  const colorBufRef = useRef<Uint8Array>(new Uint8Array(0));
  const rafRef = useRef(0);
  const hoveringRef = useRef(false);
  const dragCursorRef = useRef<number | null>(null); // pixel position

  // ── Rebuild layout + color buffer ──
  const rebuild = useCallback(() => {
    if (!data?.segments) return;
    const dpr = devicePixelRatio || 1;
    const vw = Math.round(virtualWidthRef.current * dpr);
    if (vw <= 0) return;
    layoutRef.current = buildLayout(data.segments, vw);
    colorBufRef.current = buildColorBuf(data.regions, layoutRef.current, vw);
  }, [data]);

  // ── Draw ──
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;
    const dpr = devicePixelRatio || 1;

    ctx.fillStyle = BG;
    ctx.fillRect(0, 0, w, h);

    const buf = colorBufRef.current;
    const scrollPx = Math.round(scrollOffsetRef.current * dpr);
    const vw = buf.length;
    if (vw === 0) return;

    // Draw color buffer (scrolled)
    let runStart = 0;
    let runColor = 0;
    for (let x = 0; x <= w; x++) {
      const srcX = x + scrollPx;
      const c = srcX >= 0 && srcX < vw ? buf[srcX] : 0;
      if (c !== runColor || x === w) {
        if (runColor > 0 && x > runStart) {
          ctx.fillStyle = COLOR_MAP[runColor];
          ctx.fillRect(runStart, 0, x - runStart, h);
        }
        runStart = x;
        runColor = c;
      }
    }

    // Cursor
    const cursorPx = dragCursorRef.current ??
      (currentAddr ? addrToPx(hex(currentAddr), layoutRef.current) : null);
    if (cursorPx !== null) {
      const sx = cursorPx - scrollPx;
      if (sx >= 0 && sx <= w) {
        ctx.fillStyle = CURSOR;
        ctx.fillRect(Math.round(sx) - 1, 0, 2, h);
      }
    }
  }, [currentAddr]);

  const scheduleDraw = useCallback(() => {
    cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(draw);
  }, [draw]);

  useEffect(() => { scheduleDraw(); }, [scheduleDraw]);

  // ── Container width tracking ──
  const containerWidthRef = useRef(0);

  const initVirtualWidth = useCallback(() => {
    const cw = containerRef.current?.getBoundingClientRect().width || 800;
    containerWidthRef.current = cw;
    if (virtualWidthRef.current < cw) virtualWidthRef.current = cw;
  }, []);

  // ── Fetch ──
  const fetchOverview = useCallback(() => {
    if (!activeProjectId) return;
    fetch(`/api/projects/${activeProjectId}/overview`)
      .then((r) => r.json())
      .then((d) => { if (d.regions) setData(d); })
      .catch(() => {});
  }, [activeProjectId]);

  useEffect(() => {
    if (!activeProjectId) { setData(null); return; }
    initVirtualWidth();
    scrollOffsetRef.current = 0;
    fetchOverview();
  }, [activeProjectId, fetchOverview, initVirtualWidth]);

  // Rebuild when data changes
  useEffect(() => {
    if (data) { rebuild(); scheduleDraw(); }
  }, [data, rebuild, scheduleDraw]);

  // ── Resize ──
  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;
    const observer = new ResizeObserver(() => {
      const rect = container.getBoundingClientRect();
      const dpr = devicePixelRatio || 1;
      canvas.width = Math.round(rect.width * dpr);
      canvas.height = BAR_H * dpr;
      containerWidthRef.current = rect.width;
      if (virtualWidthRef.current < rect.width) {
        virtualWidthRef.current = rect.width;
        rebuild();
      }
      scheduleDraw();
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [rebuild, scheduleDraw]);

  // ── Block browser zoom ──
  useEffect(() => {
    const block = (e: WheelEvent) => {
      if (hoveringRef.current && (e.ctrlKey || e.metaKey)) e.preventDefault();
    };
    document.addEventListener("wheel", block, { passive: false });
    return () => document.removeEventListener("wheel", block);
  }, []);

  // ── Clamp scroll ──
  const clampScroll = useCallback(() => {
    const maxScroll = Math.max(0, virtualWidthRef.current - containerWidthRef.current);
    scrollOffsetRef.current = Math.max(0, Math.min(scrollOffsetRef.current, maxScroll));
  }, []);

  // ── clientX → virtual pixel ──
  const clientXToVpx = useCallback((clientX: number): number => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return 0;
    const dpr = devicePixelRatio || 1;
    return (clientX - rect.left + scrollOffsetRef.current) * dpr;
  }, []);

  // ── Click ──
  const handleClick = useCallback((e: React.MouseEvent) => {
    const vpx = clientXToVpx(e.clientX);
    const addr = pxToAddr(vpx, layoutRef.current);
    if (addr !== null) store.setTargetAddr(ch, "0x" + addr.toString(16));
  }, [clientXToVpx, store, ch]);

  // ── Double-click reset zoom ──
  const handleDblClick = useCallback(() => {
    virtualWidthRef.current = containerWidthRef.current;
    scrollOffsetRef.current = 0;
    rebuild();
    scheduleDraw();
  }, [rebuild, scheduleDraw]);

  // ── Wheel ──
  const handleWheel = useCallback((e: React.WheelEvent) => {
    if (e.ctrlKey || e.metaKey) {
      // Zoom: change virtual width
      const factor = e.deltaY > 0 ? (1 - ZOOM_FACTOR) : (1 + ZOOM_FACTOR);
      const oldVW = virtualWidthRef.current;
      const cw = containerWidthRef.current;
      const newVW = Math.max(cw, oldVW * factor);

      // Keep mouse position stable
      const rect = canvasRef.current?.getBoundingClientRect();
      if (rect) {
        const mouseRatio = (e.clientX - rect.left + scrollOffsetRef.current) / oldVW;
        virtualWidthRef.current = newVW;
        scrollOffsetRef.current = mouseRatio * newVW - (e.clientX - rect.left);
      } else {
        virtualWidthRef.current = newVW;
      }
      clampScroll();
      rebuild();
      scheduleDraw();
    } else {
      // Scroll
      scrollOffsetRef.current += e.deltaY * 0.5;
      clampScroll();
      scheduleDraw();
    }
  }, [clampScroll, rebuild, scheduleDraw]);

  // ── Drag ──
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return;
    let lastEmit = 0;

    const onMove = (me: MouseEvent) => {
      const vpx = clientXToVpx(me.clientX);
      const addr = pxToAddr(vpx, layoutRef.current);
      if (addr === null) return;
      dragCursorRef.current = vpx;
      scheduleDraw();
      const now = performance.now();
      if (now - lastEmit > THROTTLE_MS) {
        lastEmit = now;
        store.setTargetAddr(ch, "0x" + addr.toString(16));
      }
    };
    const onUp = (me: MouseEvent) => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      dragCursorRef.current = null;
      const vpx = clientXToVpx(me.clientX);
      const addr = pxToAddr(vpx, layoutRef.current);
      if (addr !== null) store.setTargetAddr(ch, "0x" + addr.toString(16));
      scheduleDraw();
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [clientXToVpx, store, ch, scheduleDraw]);

  if (!activeProjectId) return null;

  return (
    <div className="overview-bar" ref={containerRef}>
      <canvas
        ref={canvasRef}
        style={{ width: "100%", height: BAR_H, display: "block" }}
        onClick={handleClick}
        onDoubleClick={handleDblClick}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseEnter={() => { hoveringRef.current = true; }}
        onMouseLeave={() => { hoveringRef.current = false; }}
      />
    </div>
  );
}
