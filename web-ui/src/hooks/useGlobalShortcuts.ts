import { useEffect, useRef } from "react";
import { useViewStore } from "../stores/viewStore";
import { useProjectStore } from "../stores/projectStore";
import { findTabOfType, addPanel } from "../App";

/**
 * Global keyboard shortcuts and mouse side-button bindings.
 * Mount once in App.
 */
export function useGlobalShortcuts() {
  const store = useViewStore();
  const { activeProjectId } = useProjectStore();
  // Track last clicked row's addr/token for shortcuts like X
  const lastClickedRef = useRef<{ addr: string | null; token: string | null }>({ addr: null, token: null });

  useEffect(() => {
    function onClickCapture(e: MouseEvent) {
      // Walk up from click target to find data-addr/data-token
      let el = e.target as HTMLElement | null;
      let addr: string | null = null;
      let token: string | null = null;
      while (el) {
        if (!addr) addr = el.getAttribute?.("data-addr");
        if (!token) token = el.getAttribute?.("data-token");
        if (addr || token) break;
        el = el.parentElement;
      }
      if (addr || token) {
        lastClickedRef.current = { addr, token };
      }
    }
    window.addEventListener("click", onClickCapture, true);

    function onKeyDown(e: KeyboardEvent) {
      // Ignore when typing in input/textarea
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      const ch = store.activeChannel;

      switch (e.key) {
        case "Escape":
          // Go back in navigation history
          if (activeProjectId && store.canGoBack(ch)) {
            e.preventDefault();
            store.goBack(ch, activeProjectId);
          }
          break;

        case "x":
        case "X":
          // Xrefs: query xrefs for context-appropriate target
          if (!e.ctrlKey && !e.metaKey && !e.altKey) {
            e.preventDefault();
            const last = lastClickedRef.current;
            const channel = store.getChannel(ch);
            // Xrefs always prefer address over token (token may be string content, not an IDA symbol)
            const target = last.addr || last.token || channel.targetAddr || channel.currentFunc;
            if (target) {
              if (!findTabOfType("xrefs")) addPanel("xrefs");
              store.requestXrefs(ch, target);
            }
          }
          break;

        case "g":
        case "G":
          // Go to address: open/focus search panel
          if (!e.ctrlKey && !e.metaKey && !e.altKey) {
            e.preventDefault();
            if (!findTabOfType("search")) addPanel("search");
            // Focus the search input after a tick
            requestAnimationFrame(() => {
              const input = document.querySelector(".search-input") as HTMLInputElement;
              input?.focus();
            });
          }
          break;

        case "/":
          // Search: same as G
          if (!e.ctrlKey && !e.metaKey && !e.altKey) {
            e.preventDefault();
            if (!findTabOfType("search")) addPanel("search");
            requestAnimationFrame(() => {
              const input = document.querySelector(".search-input") as HTMLInputElement;
              input?.focus();
            });
          }
          break;
      }
    }

    function onMouseDown(e: MouseEvent) {
      const ch = store.activeChannel;

      if (e.button === 3) {
        // Mouse back button → go back
        e.preventDefault();
        if (activeProjectId && store.canGoBack(ch)) {
          store.goBack(ch, activeProjectId);
        }
      } else if (e.button === 4) {
        // Mouse forward button → go forward
        e.preventDefault();
        if (activeProjectId && store.canGoForward(ch)) {
          store.goForward(ch, activeProjectId);
        }
      }
    }

    // Prevent browser default back/forward on mouse side buttons
    function onMouseUp(e: MouseEvent) {
      if (e.button === 3 || e.button === 4) {
        e.preventDefault();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("mousedown", onMouseDown);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("click", onClickCapture, true);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("mousedown", onMouseDown);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [store, activeProjectId]);
}
