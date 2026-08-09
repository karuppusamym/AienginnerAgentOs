"use client";

import {
  Activity,
  AlertCircle,
  Archive,
  Bot,
  BookOpen,
  Boxes,
  Braces,
  Check,
  ChevronDown,
  ChevronRight,
  CircleGauge,
  Clock3,
  CalendarClock,
  Code2,
  Database,
  FileSpreadsheet,
  FileUp,
  FlaskConical,
  Gauge,
  GitBranch,
  GitCompare,
  KeyRound,
  Layers3,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquare,
  Network,
  PanelLeftClose,
  Play,
  Plus,
  RefreshCw,
  Search,
  Send,
  Server,
  Settings,
  ShieldCheck,
  Sparkles,
  UserPlus,
  Users,
  X,
  XCircle,
} from "lucide-react";
import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, login, logout, SessionUser } from "./lib/api";
import type { NavKey, Overview, Recommendation, SecurityOverview, Project, ModelProvider, SearchResult, Job, Approval } from "./types";
import { navItems, navGroups, roleLanding, TOUR_STORAGE_KEY, defaultTourSteps } from "./lib/constants";
import { StatusPill, LoadingBlock, Modal } from "./components/shared";
import { LoginScreen } from "./components/LoginScreen";
import { WorkspaceView } from "./components/WorkspaceView";
import { ConversationsView } from "./components/ConversationsView";
import { DatasetsView } from "./components/DatasetsView";
import { FilesView } from "./components/FilesView";
import { SQLView } from "./components/SQLView";
import { PipelinesView } from "./components/PipelinesView";
import { JobsView } from "./components/JobsView";
import { ArtifactsView } from "./components/ArtifactsView";
import { NotebooksView } from "./components/NotebooksView";
import { EvaluationsView } from "./components/EvaluationsView";
import { QualityView } from "./components/QualityView";
import { SupersetView } from "./components/SupersetView";
import { ApprovalsView } from "./components/ApprovalsView";
import { ToolsView } from "./components/ToolsView";
import { AgentsView } from "./components/AgentsView";
import { SemanticView } from "./components/SemanticView";
import { AdminView } from "./components/admin";

export default function Home() {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [active, setActive] = useState<NavKey>("workspace");
  // Keep the workspace focused by default; the rail can be expanded from the top bar.
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [tourOpen, setTourOpen] = useState(false);
  const [tourStep, setTourStep] = useState(0);
  const [toast, setToast] = useState<{ tone: "ok" | "error"; message: string } | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [passwordForm, setPasswordForm] = useState({ current_password: "", new_password: "" });
  const [passwordDialog, setPasswordDialog] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [providers, setProviders] = useState<ModelProvider[]>([]);
  const [projectDialog, setProjectDialog] = useState(false);
  const [projectForm, setProjectForm] = useState({ name: "", description: "", environment: "local" });
  const [sqlSeed, setSqlSeed] = useState<{ question: string; dialect: string } | null>(null);
  const [pendingApprovalCount, setPendingApprovalCount] = useState(0);
  const [openNavGroups, setOpenNavGroups] = useState<Record<string, boolean>>({ overview: true, data: true, delivery: true, governance: false, administration: false });

  const notify = useCallback((message: string, tone: "ok" | "error" = "ok") => {
    setToast({ message, tone });
    window.setTimeout(() => setToast(null), 3600);
  }, []);

  useEffect(() => {
    const token = window.localStorage.getItem("datapilot_token");
    if (!token) {
      setAuthChecked(true);
      return;
    }
    api<SessionUser>("/auth/me")
      .then(setUser)
      .catch(() => logout())
      .finally(() => setAuthChecked(true));
  }, []);

  useEffect(() => {
    if (searchQuery.trim().length < 2 || !user) {
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
  }, [searchQuery, user]);

  useEffect(() => {
    if (user?.must_change_password) setPasswordDialog(true);
  }, [user?.must_change_password]);

  useEffect(() => {
    if (user) setActive(roleLanding[user.role] || "workspace");
  }, [user]);

  const loadControlPlane = useCallback(async () => {
    if (!user) return;
    try {
      const [projectData, providerData, approvalData] = await Promise.all([api<Project[]>("/projects"), api<ModelProvider[]>("/model-providers"), api<Approval[]>("/approvals?status=pending")]);
      setProjects(projectData);
      setProviders(providerData);
      setPendingApprovalCount(approvalData.length);
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : "Workspace configuration could not be loaded", "error");
    }
  }, [notify, user]);

  useEffect(() => { loadControlPlane(); }, [loadControlPlane]);

  const activeLabel = navItems.find((item) => item.key === active)?.label || "Workspace";
  const currentProject = projects.find((project) => project.is_current) || projects.find((project) => project.id === user?.current_project_id) || projects[0];
  const healthyProviders = providers.filter((provider) => provider.enabled && provider.status === "healthy");
  const visibleNavItems = navItems.filter((item) => (item.key !== "admin" || user?.role === "admin") && (item.key !== "tools" || ["admin", "engineer"].includes(user?.role || "")));
  const visibleNavGroups = navGroups.map((group) => ({ ...group, items: group.items.filter((key) => visibleNavItems.some((item) => item.key === key)) })).filter((group) => group.items.length);
  const tourSteps = defaultTourSteps.filter((step) => visibleNavItems.some((item) => item.key === step.key));
  const currentTourStep = tourSteps[tourStep] || tourSteps[0];

  useEffect(() => {
    if (!user || user.must_change_password || passwordDialog || tourOpen || !tourSteps.length) return;
    const completed = window.localStorage.getItem(TOUR_STORAGE_KEY);
    if (completed) return;
    setTourStep(0);
    setActive(tourSteps[0].key);
    setTourOpen(true);
  }, [passwordDialog, tourOpen, tourSteps, user]);

  useEffect(() => {
    if (!tourOpen || !currentTourStep) return;
    setActive(currentTourStep.key);
  }, [currentTourStep, tourOpen]);

  if (!authChecked) {
    return (
      <main className="auth-page">
        <LoadingBlock label="Opening local workspace" />
      </main>
    );
  }

  if (!user) {
    return <LoginScreen onLogin={setUser} />;
  }

  function openTour(stepIndex = 0) {
    if (!tourSteps.length) return;
    const nextStep = Math.min(Math.max(stepIndex, 0), tourSteps.length - 1);
    setTourStep(nextStep);
    setMobileNav(false);
    setTourOpen(true);
    setActive(tourSteps[nextStep].key);
  }

  function closeTour(markComplete: boolean) {
    setTourOpen(false);
    if (markComplete) {
      window.localStorage.setItem(TOUR_STORAGE_KEY, "true");
    }
  }

  async function switchProject(project: Project) {
    try {
      await api(`/projects/${project.id}/select`, { method: "POST" });
      setUser((current) => current ? { ...current, current_project_id: project.id, current_project_name: project.name } : current);
      await loadControlPlane();
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
      await loadControlPlane();
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
          {visibleNavGroups.map((group) => <div className="nav-group" key={group.key}><button className="nav-group-toggle" onClick={() => setOpenNavGroups((current) => ({ ...current, [group.key]: !current[group.key] }))}><span>{group.label}</span><ChevronDown size={14} className={openNavGroups[group.key] ? "" : "collapsed"} /></button>{openNavGroups[group.key] && group.items.map((key) => { const item = navItems.find((candidate) => candidate.key === key); if (!item) return null; const Icon = item.icon; return <button key={item.key} className={active === item.key ? "active" : ""} onClick={() => { setActive(item.key); setMobileNav(false); }} title={item.label}><Icon size={18} strokeWidth={1.8} /><span>{item.label}</span>{item.key === "approvals" && pendingApprovalCount > 0 && <span className="nav-count">{pendingApprovalCount}</span>}</button>; })}</div>)}
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
                    <button key={result.source_id} onClick={() => { setActive(result.source_type === "file" ? "files" : "datasets"); setSearchQuery(""); }}>
                      <span className="search-result-icon">{result.source_type === "file" ? <FileSpreadsheet size={16} /> : <Database size={16} />}</span>
                      <span><strong>{result.title}</strong><small>{result.text}</small></span>
                      <StatusPill value={result.source_type} />
                    </button>
                  )) : <div className="search-empty">{searching ? "Searching grounded knowledge" : "No grounded results"}</div>}
                </div>
              )}
            </div>
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
              onClick={() => {
                logout();
                setUser(null);
              }}
              aria-label="Sign out"
              title="Sign out"
            >
              <LogOut size={18} />
            </button>
          </div>
        </header>

        <main className="content">
          {active === "workspace" && <WorkspaceView setActive={setActive} notify={notify} />}
          {active === "conversations" && <ConversationsView notify={notify} currentUser={user} />}
          {active === "datasets" && <DatasetsView notify={notify} onOpenSQL={(dataset) => { setSqlSeed({ question: `Analyze ${dataset.schema_name}.${dataset.table_name} using its approved metadata`, dialect: dataset.source_name === "Local files" ? "postgres" : "sqlserver" }); setActive("sql"); }} />}
          {active === "files" && <FilesView notify={notify} currentUser={user} />}
          {active === "sql" && <SQLView notify={notify} seed={sqlSeed} currentUser={user} />}
          {active === "notebooks" && <NotebooksView notify={notify} />}
          {active === "pipelines" && <PipelinesView notify={notify} />}
          {active === "jobs" && <JobsView notify={notify} />}
          {active === "artifacts" && <ArtifactsView notify={notify} />}
          {active === "quality" && <QualityView notify={notify} />}
          {active === "superset" && <SupersetView isAdmin={user.role === "admin"} projectName={currentProject?.name || user.current_project_name || "Current project"} />}
          {active === "approvals" && <ApprovalsView notify={notify} />}
          {active === "tools" && <ToolsView notify={notify} />}
          {active === "agents" && <AgentsView notify={notify} />}
          {active === "semantic" && <SemanticView notify={notify} />}
          {active === "evaluations" && <EvaluationsView notify={notify} />}
          {active === "admin" && <AdminView currentUser={user} notify={notify} setActive={setActive} />}
        </main>
      </div>
      {mobileNav && <button className="nav-backdrop" aria-label="Close menu" onClick={() => setMobileNav(false)} />}
      {toast && (
        <div className={`toast ${toast.tone}`} role="status">
          {toast.tone === "ok" ? <Check size={18} /> : <AlertCircle size={18} />}
          {toast.message}
        </div>
      )}
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
      {projectDialog && <Modal title="Projects" onClose={() => setProjectDialog(false)}><div className="project-dialog-list">{projects.map((project) => <button key={project.id} className={project.is_current ? "selected" : ""} onClick={() => switchProject(project)}><span className="project-avatar">{project.name.split(" ").map((part) => part[0]).join("").slice(0, 2)}</span><span><strong>{project.name}</strong><small>{project.environment} / {project.membership_role || "admin"}</small></span>{project.is_current ? <Check size={17} /> : <ChevronRight size={17} />}</button>)}</div>{["admin", "engineer"].includes(user.role) && <form className="modal-form project-create-form" onSubmit={createProject}><div className="subheading"><h4>New project</h4></div><label>Name<input value={projectForm.name} onChange={(event) => setProjectForm({ ...projectForm, name: event.target.value })} required /></label><label>Description<input value={projectForm.description} onChange={(event) => setProjectForm({ ...projectForm, description: event.target.value })} /></label><div className="modal-actions"><button className="primary-button"><Plus size={17} />Create project</button></div></form>}</Modal>}
    </div>
  );
}
