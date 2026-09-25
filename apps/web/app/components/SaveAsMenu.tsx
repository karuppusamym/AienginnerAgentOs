import { Archive, ChevronDown, RefreshCw } from "lucide-react";
import { ReactNode, useEffect, useRef } from "react";

export type SaveAsItem = { key: string; label: string; icon: ReactNode; onSelect: () => void; disabled?: boolean; title?: string; busy?: boolean; hidden?: boolean };

/** One "Save as…" menu for the save/publish actions of a query (artifact, verified query, query tool, Superset…). */
export function SaveAsMenu({ items, label = "Save as…" }: { items: SaveAsItem[]; label?: string }) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    function close(event: MouseEvent | KeyboardEvent) {
      const menu = ref.current;
      if (!menu?.open) return;
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !menu.contains(event.target as Node)) menu.open = false;
    }
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, []);
  const busy = items.some((item) => item.busy);
  return (
    <details className="save-as-menu" ref={ref}>
      <summary className="secondary-button" aria-haspopup="menu">{busy ? <RefreshCw size={16} className="spin" /> : <Archive size={16} />}{label}<ChevronDown size={14} /></summary>
      <div className="save-as-list" role="menu">
        {items.filter((item) => !item.hidden).map((item) => (
          <button key={item.key} type="button" role="menuitem" disabled={item.disabled || item.busy} title={item.title} onClick={() => { if (ref.current) ref.current.open = false; item.onSelect(); }}>
            {item.busy ? <RefreshCw size={15} className="spin" /> : item.icon}<span>{item.label}</span>
          </button>
        ))}
      </div>
    </details>
  );
}
