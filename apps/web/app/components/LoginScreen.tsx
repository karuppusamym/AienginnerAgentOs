import {
  AlertCircle,
  Bot,
  ChevronRight,
  Database,
  KeyRound,
  LayoutDashboard,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { FormEvent, useState } from "react";
import { login, SessionUser } from "../lib/api";

export function LoginScreen({ onLogin, notice }: { onLogin: (user: SessionUser) => void; notice?: string }) {
  const [email, setEmail] = useState("admin@datapilot.local");
  const [password, setPassword] = useState("ChangeMe123!");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onLogin(await login(email, password));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to sign in");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="login-panel">
        <div className="login-brand">
          <div className="brand-mark large">DP</div>
          <div>
            <strong>DataPilot</strong>
            <span>Agent OS</span>
          </div>
        </div>
        <div className="login-copy">
          <h1>Open your data workspace</h1>
          <p>Sign in with a local administrator account. PingFederate can be enabled from Admin after initial setup.</p>
        </div>
        <form onSubmit={submit}>
          <label>
            Email
            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          </label>
          <label>
            Password
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required />
          </label>
          {notice && !error && <div className="form-notice" role="status"><ShieldCheck size={16} />{notice}</div>}
          {error && <div className="form-error" role="alert"><AlertCircle size={16} />{error}</div>}
          <button className="primary-button wide" disabled={busy}>
            {busy ? <RefreshCw size={17} className="spin" /> : <KeyRound size={17} />}
            Sign in
          </button>
        </form>
        <div className="login-foot">
          <ShieldCheck size={16} />
          Credentials and data remain within this local environment.
        </div>
      </section>
      <section className="auth-context">
        <div className="context-copy">
          <span className="eyebrow">GOVERNED AGENT WORKSPACE</span>
          <h2>From source systems to trusted data products.</h2>
          <p>Connect enterprise databases, profile local files, generate grounded SQL, and run controlled multi-agent workflows with a complete approval trail.</p>
        </div>
        <div className="context-flow" aria-label="Data workflow">
          <div><Database size={18} /><span>Sources</span></div>
          <ChevronRight size={16} />
          <div><Bot size={18} /><span>Agents</span></div>
          <ChevronRight size={16} />
          <div><ShieldCheck size={18} /><span>Controls</span></div>
          <ChevronRight size={16} />
          <div><LayoutDashboard size={18} /><span>Outcomes</span></div>
        </div>
      </section>
    </main>
  );
}
