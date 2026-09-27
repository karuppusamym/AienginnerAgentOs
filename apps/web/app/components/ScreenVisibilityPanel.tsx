"use client";

import { EyeOff, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { api, SESSION_REFRESH_EVENT } from "../lib/api";
import { navGroups, navItems } from "../lib/constants";
import type { Notify } from "../lib/workspace";

/** Tabs that can be hidden on their own (the page stays). */
const SUB_SCREENS: Record<string, { key: string; label: string }[]> = {
  agents: [{ key: "agents:tools", label: "Internal tools" }, { key: "agents:gateway", label: "External gateway" }, { key: "agents:history", label: "Invocation history" }],
  learning: [
    { key: "learning:verified", label: "Verified queries" }, { key: "learning:optimization", label: "Prompt optimization" },
    { key: "learning:indexes", label: "Performance & DDL" }, { key: "learning:router", label: "Router & tool choice" },
    { key: "learning:suggestions", label: "Suggestions" }, { key: "learning:evaluations", label: "Evaluations" },
  ],
};

type ScreenSettings = { project_id: string; hidden: string[]; locked: string[]; can_edit: boolean };

/** Admin → Screens: hide screens for the current project, e.g. to keep a demo focused. Presentation only. */
export function ScreenVisibilityPanel({ notify }: { notify: Notify }) {
  const [settings, setSettings] = useState<ScreenSettings | null>(null);
  const [hidden, setHidden] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    api<ScreenSettings>("/ui/screens").then((result) => { setSettings(result); setHidden(result.hidden); }).catch((reason) => notify(reason instanceof Error ? reason.message : "Screen settings could not be loaded", "error"));
  }, [notify]);
  const dirty = settings ? [...hidden].sort().join() !== [...settings.hidden].sort().join() : false;
  const toggle = (key: string) => setHidden((current) => (current.includes(key) ? current.filter((item) => item !== key) : [...current, key]));

  async function save() {
    setSaving(true);
    try {
      const result = await api<ScreenSettings>("/ui/screens", { method: "PUT", body: JSON.stringify({ hidden }) });
      setSettings(result);
      setHidden(result.hidden);
      window.dispatchEvent(new Event(SESSION_REFRESH_EVENT));
      notify(result.hidden.length ? `${result.hidden.length} screen${result.hidden.length === 1 ? "" : "s"} hidden for this project` : "All screens are visible");
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Screen settings could not be saved", "error");
    } finally {
      setSaving(false);
    }
  }

  const label = (key: string) => navItems.find((item) => item.key === key)?.label || key;
  return (
    <section className="surface admin-surface screen-visibility">
      <div className="section-heading">
        <div><span className="eyebrow">SCREENS</span><h3>Show or hide screens for this project</h3><p>Hidden screens leave the navigation for everyone in this project, which keeps a demo focused. Nothing is deleted or disabled: data, APIs and permissions are unchanged, and a screen comes back as soon as you show it. Admin always stays visible.</p></div>
        <div className="row-actions">
          <button className="secondary-button" onClick={() => setHidden([])} disabled={!hidden.length || saving}>Show all</button>
          <button className="primary-button" onClick={() => void save()} disabled={!dirty || saving || !settings?.can_edit}>{saving ? <RefreshCw size={16} className="spin" /> : <EyeOff size={16} />}{saving ? "Saving" : "Save"}</button>
        </div>
      </div>
      <div className="screen-groups">
        {navGroups.map((group) => (
          <fieldset key={group.key} className="screen-group">
            <legend>{group.label}</legend>
            {group.items.map((key) => {
              const locked = settings?.locked.includes(key) ?? key === "admin";
              const shown = !hidden.includes(key);
              return (
                <div key={key} className="screen-item">
                  <label className={`screen-toggle${shown ? "" : " off"}`}>
                    <input id={`screen-${key}`} type="checkbox" checked={shown} disabled={locked || !settings?.can_edit} onChange={() => toggle(key)} />
                    <span>{label(key)}</span>
                    <small>{locked ? "always shown" : shown ? "shown" : "hidden"}</small>
                  </label>
                  {(SUB_SCREENS[key] || []).map((sub) => {
                    const subShown = shown && !hidden.includes(sub.key);
                    return (
                      <label key={sub.key} className={`screen-toggle sub${subShown ? "" : " off"}`}>
                        <input id={`screen-${sub.key.replace(":", "-")}`} type="checkbox" checked={subShown} disabled={!shown || !settings?.can_edit} onChange={() => toggle(sub.key)} />
                        <span>{sub.label}</span>
                        <small>{!shown ? "page hidden" : subShown ? "tab shown" : "tab hidden"}</small>
                      </label>
                    );
                  })}
                </div>
              );
            })}
          </fieldset>
        ))}
      </div>
    </section>
  );
}
