import { useCallback } from "react";
import { useViewStore } from "../stores/viewStore";
import { useProjectStore } from "../stores/projectStore";
import { showContextMenu, extractContext, type ContextMenuItem } from "../components/ContextMenu";
import { findTabOfType, addPanel } from "../App";

function copyText(text: string) {
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text);
  } else {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
  }
}

/**
 * Hook for code view panels. Returns an onContextMenu handler
 * that shows a context menu with Copy Address, Copy Token, Xrefs, Navigate.
 */
export function useCodeContextMenu(channel?: string) {
  const store = useViewStore();
  const { activeProjectId } = useProjectStore();

  return useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      const { token, addr } = extractContext(e.target as HTMLElement);
      if (!token && !addr) return;

      const ch = channel || store.activeChannel;
      const items: ContextMenuItem[] = [];

      if (addr) {
        items.push({
          label: `Copy address  ${addr}`,
          onClick: () => copyText(addr),
        });
      }

      if (token && token !== addr) {
        items.push({
          label: `Copy "${token.length > 24 ? token.slice(0, 24) + "…" : token}"`,
          onClick: () => copyText(token),
        });
      }

      if (items.length > 0) {
        items.push({ label: "", onClick: () => {}, separator: true });
      }

      const target = token || addr;
      if (target && activeProjectId) {
        items.push({
          label: "Xrefs to...",
          onClick: () => {
            if (!findTabOfType("xrefs")) {
              addPanel("xrefs");
            }
            store.requestXrefs(ch, target);
          },
        });
        items.push({
          label: "Go to definition",
          onClick: () => {
            store.navigateTo(ch, activeProjectId, target);
          },
        });
      }

      if (items.length > 0) {
        showContextMenu(e.clientX, e.clientY, items);
      }
    },
    [store, channel, activeProjectId],
  );
}
