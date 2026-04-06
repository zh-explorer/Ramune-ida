import { useCallback, useEffect, useRef, useState } from "react";

export interface ContextMenuItem {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  separator?: boolean;
}

interface ContextMenuState {
  x: number;
  y: number;
  items: ContextMenuItem[];
}

let _setMenu: ((state: ContextMenuState | null) => void) | null = null;

/** Show a context menu at the given position. */
export function showContextMenu(x: number, y: number, items: ContextMenuItem[]) {
  _setMenu?.({ x, y, items });
}

/** Close the context menu. */
export function hideContextMenu() {
  _setMenu?.(null);
}

/**
 * Extract token and address from a right-click target element.
 * Walks up the DOM to find data-addr on a parent line element.
 */
export function extractContext(target: HTMLElement): { token: string | null; addr: string | null } {
  const token = target.getAttribute?.("data-token") || null;
  let addr: string | null = null;
  let el: HTMLElement | null = target;
  while (el) {
    const a = el.getAttribute?.("data-addr");
    if (a) { addr = a; break; }
    el = el.parentElement;
  }
  return { token, addr };
}

/** Mount this once at the App level. Renders the floating context menu. */
export function ContextMenuLayer() {
  const [menu, setMenu] = useState<ContextMenuState | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    _setMenu = setMenu;
    return () => { _setMenu = null; };
  }, []);

  // Close on any click or Escape
  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", onKey);
    };
  }, [menu]);

  // Clamp to viewport
  const style = menu ? (() => {
    const x = Math.min(menu.x, window.innerWidth - 200);
    const y = Math.min(menu.y, window.innerHeight - menu.items.length * 28 - 8);
    return { left: x, top: y };
  })() : undefined;

  if (!menu) return null;

  return (
    <div ref={ref} className="ctx-menu" style={style}
      onMouseDown={(e) => e.stopPropagation()}
    >
      {menu.items.map((item, i) =>
        item.separator ? (
          <div key={i} className="menu-separator" />
        ) : (
          <button key={i} className="menu-item" disabled={item.disabled}
            onClick={() => { item.onClick(); setMenu(null); }}
          >
            {item.label}
          </button>
        ),
      )}
    </div>
  );
}
