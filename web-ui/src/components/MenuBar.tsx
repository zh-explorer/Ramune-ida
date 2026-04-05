import { useCallback, useEffect, useRef, useState } from "react";
import { themes, applyTheme, getStoredThemeId } from "../theme/themes";

// ── Dropdown menu primitive ────────────────────────────────────

interface MenuItem {
  label: string;
  onClick?: () => void;
  checked?: boolean;
  separator?: boolean;
  submenu?: MenuItem[];
}

function MenuDropdown({
  items,
  onClose,
}: {
  items: MenuItem[];
  onClose: () => void;
}) {
  return (
    <div className="menu-dropdown" onMouseLeave={onClose}>
      {items.map((item, i) =>
        item.separator ? (
          <div key={i} className="menu-separator" />
        ) : item.submenu ? (
          <SubMenu key={i} item={item} />
        ) : (
          <button
            key={i}
            className="menu-item"
            onClick={() => {
              item.onClick?.();
              onClose();
            }}
          >
            {item.checked !== undefined && (
              <span className="menu-check">{item.checked ? "●" : ""}</span>
            )}
            <span>{item.label}</span>
          </button>
        ),
      )}
    </div>
  );
}

function SubMenu({ item }: { item: MenuItem }) {
  const [open, setOpen] = useState(false);

  return (
    <div
      className="menu-item has-submenu"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <span>{item.label}</span>
      <span className="menu-arrow">▶</span>
      {open && item.submenu && (
        <div className="menu-submenu">
          {item.submenu.map((sub, i) => (
            <button
              key={i}
              className="menu-item"
              onClick={() => sub.onClick?.()}
            >
              {sub.checked !== undefined && (
                <span className="menu-check">{sub.checked ? "●" : ""}</span>
              )}
              <span>{sub.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Top-level menu item ────────────────────────────────────────

function TopMenuItem({
  label,
  items,
}: {
  label: string;
  items: MenuItem[];
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="menu-top-item">
      <button
        className={`menu-top-btn ${open ? "active" : ""}`}
        onClick={() => setOpen(!open)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      >
        {label}
      </button>
      {open && <MenuDropdown items={items} onClose={() => setOpen(false)} />}
    </div>
  );
}

// ── MenuBar ────────────────────────────────────────────────────

interface MenuBarProps {
  onAddPanel: (type: string) => void;
  onResetLayout: () => void;
}

export function MenuBar({ onAddPanel, onResetLayout }: MenuBarProps) {
  const [currentTheme, setCurrentTheme] = useState(getStoredThemeId);

  const handleTheme = useCallback((id: string) => {
    applyTheme(id);
    setCurrentTheme(id);
  }, []);

  // Apply theme on mount
  useEffect(() => {
    applyTheme(currentTheme);
  }, []); // eslint-disable-line

  const viewItems: MenuItem[] = [
    {
      label: "Disassembly",
      submenu: [
        { label: "IDA View", onClick: () => onAddPanel("idaview") },
        { label: "Disassembly", onClick: () => onAddPanel("disassembly") },
        { label: "Hex View", onClick: () => onAddPanel("hex") },
      ],
    },
    {
      label: "Decompiler",
      submenu: [
        { label: "Decompile", onClick: () => onAddPanel("decompile") },
      ],
    },
    {
      label: "Navigation",
      submenu: [
        { label: "Functions", onClick: () => onAddPanel("functions") },
        { label: "Strings", onClick: () => onAddPanel("strings") },
        { label: "Names", onClick: () => onAddPanel("names") },
        { label: "Imports", onClick: () => onAddPanel("imports") },
        { label: "Exports", onClick: () => onAddPanel("exports") },
        { label: "Cross References", onClick: () => onAddPanel("xrefs") },
        { label: "Segments", onClick: () => onAddPanel("segments") },
        { label: "Local Types", onClick: () => onAddPanel("localtypes") },
      ],
    },
    {
      label: "General",
      submenu: [
        { label: "Project", onClick: () => onAddPanel("project") },
        { label: "Activity", onClick: () => onAddPanel("activity") },
      ],
    },
    { separator: true, label: "" },
    { label: "Reset Layout", onClick: onResetLayout },
  ];

  const themeItems: MenuItem[] = themes.map((t) => ({
    label: t.name,
    checked: currentTheme === t.id,
    onClick: () => handleTheme(t.id),
  }));

  const settingsItems: MenuItem[] = [
    { label: "Theme", submenu: themeItems },
  ];

  return (
    <div className="menu-bar">
      <TopMenuItem label="View" items={viewItems} />
      <TopMenuItem label="Settings" items={settingsItems} />
    </div>
  );
}
