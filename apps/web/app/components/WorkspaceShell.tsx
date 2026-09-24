"use client";

import {
  AlertCircle,
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  Database,
  FileSpreadsheet,
  KeyRound,
  LogOut,
  Menu,
  Monitor,
  Moon,
  PanelLeftClose,
  Plus,
  RefreshCw,
  Search,
  Sun,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { FormEvent, MouseEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, clearLegacyToken, getActiveProject, logout, onUnauthorized, SessionUser, setActiveProject } from "../lib/api";
import type { NavKey, Project, SearchResult } from "../types";
import { navItems, navGroups, roleLanding, TOUR_STORAGE_KEY, defaultTourSteps } from "../lib/constants";
import { canView, legacyViewTarget, NAV_PATHS, navKeyForPath } from "../lib/routes";
import { useWorkspace, WorkspaceContext, type AnalysisSeed, type NavigateOptions, type Notify, type SqlSeed, type WorkspaceContextValue } from "../lib/workspace";
import { scopes, useApprovals, useInvalidate, useModelProviders, useProjects, useQueryErrorToast } from "../lib/queries";
import { StatusPill, LoadingBlock, Modal } from "./shared";
import { LoginScreen } from "./LoginScreen";

type ThemeChoice = "light" | "dark" | "system";
const THEME_STORAGE_KEY = "datapilot.theme";
const THEME_LABELS: Record<ThemeChoice, string> = { light: "Light", dark: "Dark", system: "System" };
const NEXT_THEME: Record<ThemeChoice, ThemeChoice> = { system: "light", light: "dark", dark: "system" };

const landingPath = (role: string) => NAV_PATHS[roleLanding[role] || "workspace"];

/**
 * Authenticated shell shared by every workspace route (app/(workspace)/layout.tsx):
 * session check + login, role gate, toasts, and the sidebar / top bar chrome.
 * Route segments render inside it and read shared state through `useWorkspace()`.
 */
export function WorkspaceShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const [user, setUser] = useState<SessionUser | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [sessionNotice, setSessionNotice] = useState("");
  const [toast, setToast] = useState<{ tone: "ok" | "error"; message: string } | null>(null);
  const [sqlSeed, setSqlSeed] = useState<SqlSeed | null>(null);
  const [analysisSeed, setAnalysisSeed] = useState<AnalysisSeed | null>(null);
  const toastTimerRef = useRef<number | undefined>(undefined);
  const suppressErrorsRef = useRef(false);
  const roleRef = useRef("");
  const pathnameRef = useRef(pathname);
  const landedUserRef = useRef<string | null>(null);
  const hadUserRef = useRef(false);

  useEffect(() => { pathnameRef.current = pathname; }, [pathname]);

  const notify = useCallback<Notify>((message, tone = "ok") => {
    // After a 401 the login screen is shown; per-call error toasts would only be noise.
    if (tone === "error" && suppressErrorsRef.current) return;
    window.clearTimeout(toastTimerRef.current);
    setToast({ message, tone });
    toastTimerRef.current = window.setTimeout(() => setToast(null), tone === "error" ? 6000 : 3600);
  }, []);
  useEffect(() => () => window.clearTimeout(toastTimerRef.current), []);

  const navigate = useCallback((view: NavKey, options: NavigateOptions = {}) => {
    const role = roleRef.current;
    const target = role && !canView(view, role) ? roleLanding[role] || "workspace" : view;
    const current = pathnameRef.current || "";
    // Re-selecting Analysis while it is open keeps the open thread.
    if (target === "conversations" && !options.fresh && navKeyForPath(current) === "conversations") return;
    const path = NAV_PATHS[target];
    if (current === path) return;
    if (options.replace) router.replace(path); else router.push(path);
  }, [router]);

  // Pre-App-Router links (`?view=…&c=…&m=…`) keep working on any workspace route.
  useEffect(() => {
    const legacy = legacyViewTarget(window.location.search);
    if (legacy) router.replace(legacy);
  }, [router]);

  // One global handler for expired sessions: back to the login screen, no toast storm.
  useEffect(() => onUnauthorized(() => {
    suppressErrorsRef.current = true;
    window.clearTimeout(toastTimerRef.current);
    setToast(null);
    if (hadUserRef.current) setSessionNotice("Your session has ended. Sign in again to continue.");
    setUser(null);
    setAuthChecked(true);
    queryClient.clear();
  }), [queryClient]);

  useEffect(() => {
    // The session now lives in an httpOnly cookie; drop the token older builds stored.
    clearLegacyToken();
    api<SessionUser>("/auth/me")
      .then((me) => { setActiveProject(me.current_project_id); setUser(me); })
      .catch(() => setUser(null))
      .finally(() => setAuthChecked(true));
  }, []);

  useEffect(() => { roleRef.current = user?.role || ""; hadUserRef.current = !!user; }, [user]);

  // The URL wins on first load (deep link) when the role may see it; a different
  // identity signing in later lands on its role's home route.
  useEffect(() => {
    if (!user?.id) return;
    roleRef.current = user.role;
    if (landedUserRef.current === user.id) return;
    const firstIdentity = landedUserRef.current === null;
    landedUserRef.current = user.id;
    const key = navKeyForPath(pathnameRef.current);
    if (firstIdentity && key && canView(key, user.role)) return;
    router.replace(landingPath(user.role));
  }, [user?.id, user?.role, router]);

  const projectId = user?.current_project_id || "default";
  const context = useMemo<WorkspaceContextValue | null>(() => user ? {
    user,
    projectId,
    notify,
    navigate,
    analysisSeed,
    setAnalysisSeed,
    sqlSeed,
    setSqlSeed,
  } : null, [user, projectId, notify, navigate, analysisSeed, sqlSeed]);

  let body: ReactNode;
  if (!authChecked) {
    body = <main className="auth-page"><LoadingBlock label="Opening local workspace" /></main>;
  } else if (!user || !context) {
    body = <LoginScreen notice={sessionNotice} onLogin={(signedIn) => { suppressErrorsRef.current = false; setSessionNotice(""); queryClient.clear(); setActiveProject(signedIn.current_project_id); setUser(signedIn); }} />;
  } else {
    body = (
      <WorkspaceContext.Provider value={context}>
        <ShellChrome
          setUser={setUser}
          onSignedOut={() => { setSessionNotice(""); setUser(null); queryClient.clear(); }}
          clearSeeds={() => { setAnalysisSeed(null); setSqlSeed(null); }}
        >
          {children}
        </ShellChrome>
      </WorkspaceContext.Provider>
    );
  }

  return (
    <>
      {body}
      {toast && (
        <div className={`toast ${toast.tone}`} role={toast.tone === "error" ? "alert" : "status"}>
          {toast.tone === "ok" ? <Check size={18} /> : <AlertCircle size={18} />}
          <span>{toast.message}</span>
          <button type="button" className="toast-close" onClick={() => { window.clearTimeout(toastTimerRef.current); setToast(null); }} aria-label="Dismiss notification"><X size={14} /></button>
        </div>
      )}
    </>
  );
}

function ShellChrome({ children, setUser, onSignedOut, clearSeeds }: {
  children: ReactNode;
  setUser: (update: (current: SessionUser | null) => SessionUser | null) => void;
  onSignedOut: () => void;
  clearSeeds: () => void;
}) {
  const { user, notify, navigate } = useWorkspace();
  const router = useRouter();
  const pathname = usePathname();
  const invalidate = useInvalidate();
  const active = navKeyForPath(pathname);
  // Keep the workspace focused by default; the rail can be expanded from the top bar.
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [tourOpen, setTourOpen] = useState(false);
  const [tourStep, setTourStep] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [passwordForm, setPasswordForm] = useState({ current_password: "", new_password: "" });
  const [passwordDialog, setPasswordDialog] = useState(false);
  const [projectDialog, setProjectDialog] = useState(false);
  const [projectForm, setProjectForm] = useState({ name: "", description: "", environment: "local" });
  const [openNavGroups, setOpenNavGroups] = useState<Record<string, boolean>>({ overview: true, data: true, delivery: true, governance: false, administration: false });
  const [theme, setTheme] = useState<ThemeChoice>("system");
  const tourAutoRef = useRef<string | null>(null);

  const projectsQuery = useProjects();
  const providersQuery = useModelProviders();
  const pendingApprovals = useApprovals("pending");
  useQueryErrorToast(projectsQuery.error || providersQuery.error, notify, "Workspace configuration could not be loaded");
  const projects = useMemo(() => projectsQuery.data ?? [], [projectsQuery.data]);
  const providers = providersQuery.data ?? [];
  const pendingApprovalCount = pendingApprovals.data?.length ?? 0;

  // A deep link into a collapsed nav group opens that group so the active item is visible.
  useEffect(() => {
    const group = navGroups.find((item) => active && item.items.includes(active));
    if (group) setOpenNavGroups((current) => (current[group.key] ? current : { ...current, [group.key]: true }));
  }, [active]);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
      if (stored === "light" || stored === "dark") setTheme(stored);
    } catch { /* storage unavailable */ }
  }, []);

  useEffect(() => {
    const current = projects.find((project) => project.is_current);
    if (current && !getActiveProject()) setActiveProject(current.id);
  }, [projects]);

  useEffect(() => {
    if (searchQuery.trim().length < 2) {
      setSearchResults([]);
      return;
    }
    const timer = window.setTimeout(() => {
      setSearching(true);
      api<{ results: SearchResult[] }>(`/search?q=${encodeURIComponent(searchQuery.trim())}`)
        .then((result) => setSearchResults(result.results))
        .catch(() => setSearchResults([]))
        .finally(() => setSearching(false));
    }, 220);
    return () => window.clearTimeout(timer);
  }, [searchQuery]);

  useEffect(() => {
    if (user.must_change_password) setPasswordDialog(true);
  }, [user.must_change_password]);

  // Role gate: a route the role may not open redirects to the role's home route.
  const allowed = !active || canView(active, user.role);
  useEffect(() => {
    if (!allowed) router.replace(landingPath(user.role));
  }, [allowed, router, user.role]);

  const activeLabel = navItems.find((item) => item.key === active)?.label || "Workspace";
  const currentProject = projects.find((project) => project.id === user.current_project_id) || projects.find((project) => project.is_current) || projects[0];
  const healthyProviders = providers.filter((provider) => provider.enabled && provider.status === "healthy");
  const visibleNavItems = navItems.filter((item) => canView(item.key, user.role));
  const visibleNavGroups = navGroups.map((group) => ({ ...group, items: group.items.filter((key) => visibleNavItems.some((item) => item.key === key)) })).filter((group) => group.items.length);
  const tourSteps = defaultTourSteps.filter((step) => visibleNavItems.some((item) => item.key === step.key));
  const currentTourStep = tourSteps[tourStep] || tourSteps[0];
  const currentTourKey = currentTourStep?.key;
  const tourStepCount = tourSteps.length;
  const firstTourKey = tourSteps[0]?.key;

  // Auto-open the tour once per signed-in user; dismissing it keeps it closed for this session.
  useEffect(() => {
    if (user.must_change_password || passwordDialog || tourOpen || !tourStepCount || !firstTourKey) return;
    if (tourAutoRef.current === user.id) return;
    let completed: string | null = null;
    try { completed = window.localStorage.getItem(TOUR_STORAGE_KEY); } catch { completed = "unavailable"; }
    tourAutoRef.current = user.id;
    if (completed) return;
    setTourStep(0);
    navigate(firstTourKey, { replace: true });
    setTourOpen(true);
  }, [passwordDialog, tourOpen, tourStepCount, firstTourKey, user.id, user.must_change_password, navigate]);

  useEffect(() => {
    if (!tourOpen || !currentTourKey) return;
    navigate(currentTourKey, { replace: true });
  }, [currentTourKey, tourOpen, navigate]);

  function openTour(stepIndex = 0) {
    if (!tourSteps.length) return;
    const nextStep = Math.min(Math.max(stepIndex, 0), tourSteps.length - 1);
    setTourStep(nextStep);
    setMobileNav(false);
    setTourOpen(true);
    navigate(tourSteps[nextStep].key, { replace: true });
  }

  function closeTour(markComplete: boolean) {
    setTourOpen(false);
    if (markComplete) {
      try { window.localStorage.setItem(TOUR_STORAGE_KEY, "true"); } catch { /* storage unavailable */ }
    }
  }

  function chooseTheme(next: ThemeChoice) {
    setTheme(next);
    const root = document.documentElement;
    if (next === "system") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", next);
    try {
      if (next === "system") window.localStorage.removeItem(THEME_STORAGE_KEY); else window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch { /* storage unavailable */ }
  }

  async function signOut() {
    await logout();
    onSignedOut();
  }

  async function switchProject(project: Project) {
    try {
      await api(`/projects/${project.id}/select`, { method: "POST" });
      setActiveProject(project.id);
      // Seeds and the open thread belong to the previous project.
      clearSeeds();
      if (active === "conversations") router.replace(NAV_PATHS.conversations);
      // A new project id changes every query key, so no view can show the previous project's data.
      setUser((current) => current ? { ...current, current_project_id: project.id, current_project_name: project.name } : current);
      setProjectDialog(false);
      notify(`Project switched to ${project.name}`);
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Project switch failed", "error"); }
  }
  async function createProject(event: FormEvent) {
    event.preventDefault();
    try {
      const project = await api<Project>("/projects", { method: "POST", body: JSON.stringify(projectForm) });
      setProjectForm({ name: "", description: "", environment: "local" });
      await switchProject(project);
      notify("Project created and selected");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Project creation failed", "error"); }
  }
  async function selectModel(providerId: string) {
    if (!currentProject) return;
    try {
      await api(`/projects/${currentProject.id}/model-provider`, { method: "PUT", body: JSON.stringify({ provider_id: providerId }) });
      await invalidate(scopes.projects, scopes.modelRouting);
      notify("Project model updated");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Model selection failed", "error"); }
  }
  async function changePassword(event: FormEvent) {
    event.preventDefault();
    try {
      await api("/auth/change-password", { method: "POST", body: JSON.stringify(passwordForm) });
      setUser((current) => current ? { ...current, must_change_password: false } : current);
      setPasswordForm({ current_password: "", new_password: "" });
      setPasswordDialog(false);
      notify("Password changed");
    } catch (reason) { notify(reason instanceof Error ? reason.message : "Password change failed", "error"); }
  }
  function onNavClick(event: MouseEvent<HTMLAnchorElement>, key: NavKey) {
    setMobileNav(false);
    // Re-selecting Analysis from the nav keeps the open thread instead of starting a new one.
    if (key === "conversations" && active === "conversations" && !event.metaKey && !event.ctrlKey && !event.shiftKey) event.preventDefault();
  }
  // Views remount on project switch so no view keeps local state from the previous project.
  const projectKey = user.current_project_id || "default";
  const ThemeIcon = theme === "dark" ? Moon : theme === "light" ? Sun : Monitor;
  return (
    <div className={`app-shell ${sidebarOpen ? "" : "sidebar-collapsed"}`}>
      <aside className={`sidebar ${mobileNav ? "mobile-open" : ""}`}>
        <div className="brand">
          <div className="brand-mark">DP</div>
          <div className="brand-copy">
            <strong>DataPilot</strong>
            <span>Agent OS</span>
          </div>
          <button className="icon-button sidebar-close" onClick={() => setMobileNav(false)} aria-label="Close menu">
            <X size={19} />
          </button>
        </div>
        <div className="project-switcher">
          <span className="project-label">Project</span>
          <button onClick={() => setProjectDialog(true)} title="Switch or create project">
            <span className="project-avatar">RB</span>
            <span>
              <strong>{currentProject?.name || user.current_project_name || "Select project"}</strong>
              <small>{currentProject?.environment || "local"} environment</small>
            </span>
            <ChevronDown size={16} />
          </button>
        </div>
        <nav className="main-nav" aria-label="Product navigation">
          {visibleNavGroups.map((group) => (
            <div className="nav-group" key={group.key}>
              <button className="nav-group-toggle" aria-expanded={!!openNavGroups[group.key]} onClick={() => setOpenNavGroups((current) => ({ ...current, [group.key]: !current[group.key] }))}><span>{group.label}</span><ChevronDown size={14} className={openNavGroups[group.key] ? "" : "collapsed"} /></button>
              {openNavGroups[group.key] && group.items.map((key) => {
                const item = navItems.find((candidate) => candidate.key === key);
                if (!item) return null;
                const Icon = item.icon;
                return (
                  <Link key={item.key} href={NAV_PATHS[item.key]} className={`nav-link${active === item.key ? " active" : ""}`} aria-current={active === item.key ? "page" : undefined} onClick={(event) => onNavClick(event, item.key)} title={item.label}>
                    <Icon size={18} strokeWidth={1.8} /><span>{item.label}</span>{item.key === "approvals" && pendingApprovalCount > 0 && <span className="nav-count">{pendingApprovalCount}</span>}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="local-status">
            <span className="status-dot" />
            <span>
              <strong>Local stack</strong>
              <small>Private workspace</small>
            </span>
          </div>
          <button className="user-menu" onClick={() => setPasswordDialog(true)} title="Account and password">
            <span className="user-avatar">{user.name.split(" ").map((part) => part[0]).join("").slice(0, 2)}</span>
            <span>
              <strong>{user.name}</strong>
              <small>{user.role}</small>
            </span>
            <KeyRound size={16} />
          </button>
        </div>
      </aside>

      <div className="app-body">
        <header className="topbar">
          <div className="topbar-left">
            <button className="icon-button mobile-menu" onClick={() => setMobileNav(true)} aria-label="Open menu">
              <Menu size={20} />
            </button>
            <button
              className="icon-button desktop-collapse"
              onClick={() => setSidebarOpen((value) => !value)}
              aria-label={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
              title={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
            >
              <PanelLeftClose size={19} />
            </button>
            <div>
              <h1>{activeLabel}</h1>
              <p>{currentProject?.name || "Local workspace"} / {currentProject?.environment || "local"}</p>
            </div>
          </div>
          <div className="topbar-actions">
            <select className="topbar-model-select" value={currentProject?.default_model_provider_id || ""} onChange={(event) => selectModel(event.target.value)} disabled={!currentProject || !healthyProviders.length || !["admin", "engineer"].includes(user.role)} aria-label="Active project model" title="Active project model">
              {!healthyProviders.length && <option value="">No tested models</option>}
              {healthyProviders.map((provider) => <option key={provider.id} value={provider.id}>{provider.name} / {provider.default_model}</option>)}
            </select>
            <div className="global-search">
              <div className="search-box">
                {searching ? <RefreshCw size={17} className="spin" /> : <Search size={17} />}
                <input aria-label="Search workspace" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="Search datasets, files, knowledge" />
              </div>
              {searchQuery.trim().length >= 2 && (
                <div className="search-results">
                  {searchResults.length ? searchResults.map((result) => (
                    <button key={result.source_id} onClick={() => { navigate(result.source_type === "file" ? "files" : "datasets"); setSearchQuery(""); }}>
                      <span className="search-result-icon">{result.source_type === "file" ? <FileSpreadsheet size={16} /> : <Database size={16} />}</span>
                      <span><strong>{result.title}</strong><small>{result.text}</small></span>
                      <StatusPill value={result.source_type} />
                    </button>
                  )) : <div className="search-empty">{searching ? "Searching grounded knowledge" : "No grounded results"}</div>}
                </div>
              )}
            </div>
            <button
              className="icon-button theme-toggle"
              onClick={() => chooseTheme(NEXT_THEME[theme])}
              aria-label={`Theme: ${THEME_LABELS[theme]}. Switch to ${THEME_LABELS[NEXT_THEME[theme]]}`}
              title={`Theme: ${THEME_LABELS[theme]} (click for ${THEME_LABELS[NEXT_THEME[theme]]})`}
            >
              <ThemeIcon size={18} />
            </button>
            <button
              className="icon-button"
              onClick={() => openTour(0)}
              aria-label="Open product tour"
              title="Open product tour"
            >
              <BookOpen size={18} />
            </button>
            <button
              className="icon-button"
              onClick={() => void signOut()}
              aria-label="Sign out"
              title="Sign out"
            >
              <LogOut size={18} />
            </button>
          </div>
        </header>

        <main className="content" key={projectKey}>
          {allowed ? children : <LoadingBlock label="Opening your home view" />}
        </main>
      </div>
      {mobileNav && <button className="nav-backdrop" aria-label="Close menu" onClick={() => setMobileNav(false)} />}
      {tourOpen && currentTourStep && (
        <Modal title="Product tour" onClose={() => closeTour(false)}>
          <div className="tour-body">
            <div className="tour-progress">
              <span>Step {tourStep + 1} of {tourSteps.length}</span>
              <strong>{currentTourStep.title}</strong>
            </div>
            <p className="tour-copy">{currentTourStep.body}</p>
            <div className="tour-step-list">
              {tourSteps.map((step, index) => (
                <button
                  key={step.key}
                  className={index === tourStep ? "active" : ""}
                  onClick={() => openTour(index)}
                  type="button"
                >
                  <span>{index + 1}</span>
                  <strong>{visibleNavItems.find((item) => item.key === step.key)?.label || step.title}</strong>
                </button>
              ))}
            </div>
            <div className="modal-actions">
              <button type="button" className="secondary-button" onClick={() => closeTour(true)}>Skip tour</button>
              <button type="button" className="secondary-button" onClick={() => setTourStep((value) => Math.max(0, value - 1))} disabled={tourStep === 0}>Back</button>
              {tourStep < tourSteps.length - 1 ? (
                <button type="button" className="primary-button" onClick={() => setTourStep((value) => Math.min(tourSteps.length - 1, value + 1))}>
                  Next
                </button>
              ) : (
                <button type="button" className="primary-button" onClick={() => closeTour(true)}>
                  Finish
                </button>
              )}
            </div>
          </div>
        </Modal>
      )}
      {passwordDialog && <Modal title={user.must_change_password ? "Change temporary password" : "Change password"} onClose={() => setPasswordDialog(false)}><form className="modal-form" onSubmit={changePassword}><label>Current password<input type="password" value={passwordForm.current_password} onChange={(event) => setPasswordForm({ ...passwordForm, current_password: event.target.value })} required /></label><label>New password<input type="password" value={passwordForm.new_password} onChange={(event) => setPasswordForm({ ...passwordForm, new_password: event.target.value })} minLength={10} required /></label><div className="modal-actions"><button className="primary-button"><KeyRound size={17} />Change password</button></div></form></Modal>}
      {projectDialog && <Modal title="Projects" onClose={() => setProjectDialog(false)}><div className="project-dialog-list">{projects.map((project) => <button key={project.id} className={project.id === currentProject?.id ? "selected" : ""} onClick={() => switchProject(project)}><span className="project-avatar">{project.name.split(" ").map((part) => part[0]).join("").slice(0, 2)}</span><span><strong>{project.name}</strong><small>{project.environment} / {project.membership_role || "admin"}</small></span>{project.id === currentProject?.id ? <Check size={17} /> : <ChevronRight size={17} />}</button>)}</div>{["admin", "engineer"].includes(user.role) && <form className="modal-form project-create-form" onSubmit={createProject}><div className="subheading"><h4>New project</h4></div><label>Name<input value={projectForm.name} onChange={(event) => setProjectForm({ ...projectForm, name: event.target.value })} required /></label><label>Description<input value={projectForm.description} onChange={(event) => setProjectForm({ ...projectForm, description: event.target.value })} /></label><div className="modal-actions"><button className="primary-button"><Plus size={17} />Create project</button></div></form>}</Modal>}
    </div>
  );
}
