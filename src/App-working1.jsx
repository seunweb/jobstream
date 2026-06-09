import { useState, useEffect, useCallback, useRef } from "react";
// Auth helpers - safe inline implementation
function getStoredUser() { try { return JSON.parse(localStorage.getItem("js_user")); } catch { return null; } }
function getAccessToken() { return localStorage.getItem("js_access_token"); }
function clearAuth() { ["js_access_token","js_refresh_token","js_user"].forEach(k => localStorage.removeItem(k)); }
async function apiLogout(rt) { try { await fetch(`${API}/auth/logout`, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({refresh_token: rt}) }); } catch {} }

// ── Config ──────────────────────────────────────────────────────────────────
const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function api(path, opts = {}) {
  const token = getAccessToken();
  const headers = { "Content-Type": "application/json", ...opts.headers };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${API}${path}`, { ...opts, headers });
  if (res.status === 401) {
    clearAuth();
    window.location.reload();
    return;
  }
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  if (res.status === 204) return null;
  return res.json();
}

// ── Colour palette per company initial ─────────────────────────────────────
const LOGO_COLORS = [
  { bg: "#1a1a2e", fg: "#0071E3" },
  { bg: "#0f2318", fg: "#3DD68C" },
  { bg: "#2a1a0a", fg: "#F5A623" },
  { bg: "#1e1020", fg: "#e879f9" },
  { bg: "#0a1e2a", fg: "#38bdf8" },
  { bg: "#1a2010", fg: "#86efac" },
];

function logoColor(str = "") {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) >>> 0;
  return LOGO_COLORS[h % LOGO_COLORS.length];
}

function initials(name = "") {
  return name.split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase();
}

// Custom logo overrides — add company name key (lowercase no spaces) → URL
const CUSTOM_LOGOS = {
  "t2mobile": "https://www.t2mobile.com.ng/_next/static/media/logos.1d851e63.png",
};

function getCustomLogo(name) {
  if (!name) return null;
  const key = name.toLowerCase().replace(/[^a-z0-9]/g, "");
  for (const [k, v] of Object.entries(CUSTOM_LOGOS)) {
    if (k.replace(/[^a-z0-9]/g, "") === key) return v;
  }
  return null;
}

// Company logo — tries multiple logo sources with fallback chain
function CompanyLogo({ name, sourceUrl, size = 42 }) {
  const lc = logoColor(name);
  const ini = initials(name);
  const [srcIndex, setSrcIndex] = useState(0);

  const customUrl = getCustomLogo(name);

  let domain = "";
  try {
    if (sourceUrl) domain = new URL(sourceUrl).hostname.replace("www.", "");
  } catch {}

  // Try multiple sources in order
  const sources = [
    customUrl,
    domain ? `https://logo.clearbit.com/${domain}` : null,
    domain ? `https://www.google.com/s2/favicons?domain=${domain}&sz=128` : null,
    domain ? `https://icons.duckduckgo.com/ip3/${domain}.ico` : null,
  ].filter(Boolean);

  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  const cr = 8 + (h % 6);

  const currentSrc = sources[srcIndex];

  if (currentSrc) {
    return (
      <div style={{ width: size, height: size, borderRadius: cr, background: "transparent", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <img
          src={currentSrc}
          alt={name}
          onError={() => {
            if (srcIndex < sources.length - 1) {
              setSrcIndex(srcIndex + 1);
            } else {
              setSrcIndex(sources.length); // show fallback
            }
          }}
          style={{ width: size * 0.75, height: size * 0.75, objectFit: "contain", display: "block" }}
        />
      </div>
    );
  }

  // Fallback: styled initials
  return (
    <div style={{ width: size, height: size, borderRadius: cr, background: lc.bg, color: lc.fg, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: size * 0.33, fontWeight: 700 }}>
      {ini}
    </div>
  );
}


// ── Job Card ─────────────────────────────────────────────────────────────────
// Determine if a job accepts direct applications on JobStream
// Rules:
// - Scraped jobs (source === "scraped" or has source_url) → always redirect to company website
// - Manually posted jobs with no source_url → accept direct JobStream applications
// - If apply_url === source_url → no individual job URL found, redirect to company website
function hasDirectApply(job) {
  // Manually posted jobs on JobStream (no source_url = posted directly)
  if (!job.source_url && !job.apply_url) return true;
  if (!job.source_url && job.apply_url) return true;

  // Scraped jobs — always redirect to company website
  if (job.source === "scraped") return false;

  // If apply_url is missing or same as source listing page → redirect
  if (!job.apply_url) return false;
  try {
    const normalize = (u) => u.trim().replace(/\/+$/, "").toLowerCase();
    if (normalize(job.apply_url) === normalize(job.source_url)) return false;
    const a = new URL(job.apply_url);
    const s = new URL(job.source_url);
    // Same host + same/shorter path = still on listing page
    if (a.hostname === s.hostname) {
      const aPath = a.pathname.replace(/\/+$/, "");
      const sPath = s.pathname.replace(/\/+$/, "");
      if (aPath === sPath) return false;
      if (aPath.length <= sPath.length) return false;
    }
  } catch { return false; }

  // Has a unique job-level URL but was scraped → still redirect to company
  if (job.source_url) return false;

  return true;
}

function JobCard({ job, onApply, onView, isExpanded, isDark = true, user, onAuthRequired }) {
  const isNew = (() => {
    try { return (Date.now() - new Date(job.created_at).getTime()) < 86400000 * 2; } catch { return false; }
  })();

  const postedDate = job.scraped_at
    ? new Date(job.scraped_at).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" })
    : "—";

  return (
    <div style={{
      background: isDark ? "#141416" : "#ffffff", border: isExpanded ? "1px solid #0071E3" : (isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8"), borderRadius: 14,
      overflow: "hidden", transition: "border-color 0.15s, background 0.2s",
    }}>
      {/* Card header - always visible */}
      <div
        style={{ padding: "18px 20px", cursor: "pointer" }}
        onClick={() => onView(job)}
        onMouseEnter={(e) => e.currentTarget.style.background = isDark ? "#1a1a1e" : "#f5f5f8"}
        onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
      >
        <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
          <CompanyLogo name={job.company} sourceUrl={job.source_url} size={42} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 18, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 4, letterSpacing: -0.4, lineHeight: 1.3 }}>{job.title}</div>
            <div style={{ fontSize: 12, color: isDark ? "#666" : "#555" }}>{job.company}</div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
            {isNew && <Chip variant="green" isDark={isDark}>New</Chip>}
            <span style={{ fontSize: 14, color: "#555", transition: "transform 0.2s", display: "inline-block", transform: isExpanded ? "rotate(180deg)" : "rotate(0deg)" }}>⌄</span>
          </div>
        </div>

        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 14 }}>
          <Chip isDark={isDark}>📍 {job.location}</Chip>
          <Chip isDark={isDark}>{job.job_type}</Chip>
          {job.salary && <Chip isDark={isDark}>💰 {job.salary}</Chip>}
          <Chip variant="accent" isDark={isDark}>{job.department}</Chip>
        </div>

        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 14, paddingTop: 14, borderTop: "1px solid #1e1e24" }}>
          <span style={{ fontSize: 11, color: isDark ? "#555" : "#888", fontFamily: "'DM Mono', monospace" }}>
            Posted on {postedDate}
          </span>
          <button
            onClick={(e) => {
              e.stopPropagation();
              if (!hasDirectApply(job)) return; // grayed out
              if (!user) { onAuthRequired(); return; } // require login
              onApply(job);
            }}
            disabled={!hasDirectApply(job)}
            title={!hasDirectApply(job) ? "Apply on company website →" : !user ? "Sign in to apply" : "Apply now"}
            style={{
              background: !hasDirectApply(job) ? (isDark ? "#2a2a32" : "#e0e0e0") : "#0071E3",
              border: "none", borderRadius: 8,
              padding: "7px 16px", fontSize: 12, fontWeight: 500,
              color: !hasDirectApply(job) ? (isDark ? "#555" : "#999") : "#fff",
              cursor: !hasDirectApply(job) ? "not-allowed" : "pointer",
              fontFamily: "'DM Sans', sans-serif", transition: "background 0.15s",
              opacity: !hasDirectApply(job) ? 0.6 : 1,
            }}
            onMouseEnter={(e) => { if (hasDirectApply(job)) e.currentTarget.style.background = "#0077ED"; }}
            onMouseLeave={(e) => { if (hasDirectApply(job)) e.currentTarget.style.background = "#0071E3"; }}
          >
            {!hasDirectApply(job) ? "Apply on site →" : !user ? "Sign in to apply" : "Apply now →"}
          </button>
        </div>
      </div>

      {/* Inline expanded detail */}
      {isExpanded && (
        <div style={{ borderTop: "1px solid #2a2a32", padding: "20px 24px", background: isDark ? "#111113" : "#f8f8fb" }}>
          {/* Description */}
          <div style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 11, color: "#555", textTransform: "uppercase", letterSpacing: "0.5px", fontWeight: 500, marginBottom: 12 }}>About this role</div>
            {job.description && job.description.trim() ? (
              <div style={{ fontSize: 13, color: isDark ? "#b0b0c0" : "#1d1d1f", lineHeight: 1.8 }}>
                {(() => {
                  const lines = job.description.trim().split("\n");
                  const elements = [];
                  let bulletGroup = [];

                  const flushBullets = () => {
                    if (bulletGroup.length > 0) {
                      elements.push(
                        <ul key={`ul-${elements.length}`} style={{ paddingLeft: 0, margin: "6px 0 10px 0", listStyle: "none" }}>
                          {bulletGroup.map((b, bi) => (
                            <li key={bi} style={{ display: "flex", gap: 10, marginBottom: 5, alignItems: "flex-start" }}>
                              <span style={{ color: "#0071E3", flexShrink: 0, fontSize: 16, lineHeight: 1.4 }}>•</span>
                              <span style={{ flex: 1 }}>{b}</span>
                            </li>
                          ))}
                        </ul>
                      );
                      bulletGroup = [];
                    }
                  };

                  lines.forEach((line, i) => {
                    if (line.startsWith("**") && line.endsWith("**")) {
                      flushBullets();
                      const headingText = line.replace(/\*\*/g, "");
                      // Detect if it's a main section heading or a sub-heading
                      const isMain = headingText === headingText.toUpperCase() && headingText.length > 3;
                      elements.push(
                        <div key={i} style={{
                          fontWeight: 700,
                          fontSize: isMain ? 14 : 13,
                          marginTop: isMain ? 24 : 14,
                          marginBottom: 8,
                          borderBottom: isMain ? "1px solid #2a2a32" : "none",
                          paddingBottom: isMain ? 6 : 0,
                          textTransform: isMain ? "uppercase" : "none",
                          letterSpacing: isMain ? "0.5px" : "normal",
                          color: isMain ? (isDark ? "#f0f0f2" : "#1d1d1f") : (isDark ? "#4DA3FF" : "#0071E3"),
                        }}>
                          {headingText}
                        </div>
                      );
                    } else if (line.startsWith("• ") || line.startsWith("• ")) {
                      bulletGroup.push(line.slice(2));
                    } else if (line.trim() === "") {
                      flushBullets();
                      elements.push(<div key={i} style={{ height: 8 }} />);
                    } else {
                      flushBullets();
                      elements.push(
                        <p key={i} style={{ margin: "0 0 8px 0", color: isDark ? "#b0b0c0" : "#1d1d1f" }}>{line}</p>
                      );
                    }
                  });

                  flushBullets();
                  return elements;
                })()}
              </div>
            ) : (
              <div style={{ fontSize: 13, color: "#555", lineHeight: 1.8 }}>
                Full description available on the company website — click <strong style={{ color: "#4DA3FF" }}>Apply on company website</strong> below to view it.
              </div>
            )}
          </div>

          {/* Action buttons */}
          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", paddingTop: 16, borderTop: isDark ? "1px solid #2a2a32" : "1px solid #e8e8e8" }}>
            <button onClick={() => onView(job)} style={{ background: "none", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 8, padding: "9px 16px", fontSize: 13, color: "#888", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>
              Close
            </button>
            {job.apply_url && (
              <a href={job.apply_url} target="_blank" rel="noreferrer" style={{ background: isDark ? "#1e1e2e" : "#e8e8ed", border: isDark ? "1px solid rgba(0,113,227,0.35)" : "1px solid #c7c7cc", borderRadius: 8, padding: "9px 16px", fontSize: 13, color: isDark ? "#4DA3FF" : "#1d1d1f", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", textDecoration: "none", fontWeight: 500 }}>
                Apply on company website →
              </a>
            )}
            <button
              onClick={() => {
                if (!hasDirectApply(job)) return;
                if (!user) { onAuthRequired(); return; }
                onApply(job);
              }}
              disabled={!hasDirectApply(job)}
              title={!hasDirectApply(job) ? "Apply on company website →" : !user ? "Sign in to apply" : "Apply now"}
              style={{
                background: !hasDirectApply(job) ? (isDark ? "#2a2a32" : "#e0e0e0") : "#0071E3",
                border: "none", borderRadius: 8, padding: "9px 20px", fontSize: 13, fontWeight: 500,
                color: !hasDirectApply(job) ? (isDark ? "#555" : "#999") : "#fff",
                cursor: !hasDirectApply(job) ? "not-allowed" : "pointer",
                fontFamily: "'DM Sans', sans-serif",
                opacity: !hasDirectApply(job) ? 0.6 : 1,
              }}
            >
              {!hasDirectApply(job) ? "Apply on site →" : !user ? "Sign in to apply" : "Apply now →"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Pages ─────────────────────────────────────────────────────────────────────
// ── Apply Modal ──────────────────────────────────────────────────────────────
// ── Reset Password Modal ─────────────────────────────────────────────────────
function ResetPasswordModal({ token, onClose, onSuccess }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const inp = {
    width: "100%", boxSizing: "border-box", padding: "11px 14px",
    fontSize: 14, border: "1px solid #d0d0d8", borderRadius: 10,
    background: "#fff", color: "#1d1d1f",
    fontFamily: "'DM Sans', sans-serif", outline: "none", marginTop: 6,
  };

  async function handleSubmit(e) {
    e.preventDefault();
    if (password.length < 8) { setError("Password must be at least 8 characters"); return; }
    if (password !== confirm) { setError("Passwords do not match"); return; }
    setLoading(true); setError("");
    try {
      const res = await fetch(`${API}/auth/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, new_password: password }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Reset failed");
      onSuccess();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 9000, padding: 20 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: "#fff", borderRadius: 20, padding: "36px 32px", width: "100%", maxWidth: 400, boxShadow: "0 20px 60px rgba(0,0,0,0.2)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 24 }}>
          <div style={{ width: 30, height: 30, background: "#0071E3", borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14 }}>⚡</div>
          <span style={{ fontSize: 17, fontWeight: 700, color: "#1d1d1f" }}>JobStream</span>
        </div>
        <h2 style={{ fontSize: 22, fontWeight: 700, color: "#1d1d1f", marginBottom: 4, letterSpacing: -0.5 }}>Choose new password</h2>
        <p style={{ fontSize: 13, color: "#888", marginBottom: 24 }}>Enter and confirm your new password below.</p>
        {error && <div style={{ background: "#fff0f0", border: "1px solid #f5c6c6", borderRadius: 8, padding: "10px 14px", marginBottom: 16, fontSize: 13, color: "#c0392b" }}>{error}</div>}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <label style={{ fontSize: 11, color: "#666", textTransform: "uppercase", letterSpacing: "0.4px", fontWeight: 500 }}>New password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Min. 8 characters" required style={inp} />
          </div>
          <div style={{ marginBottom: 20 }}>
            <label style={{ fontSize: 11, color: "#666", textTransform: "uppercase", letterSpacing: "0.4px", fontWeight: 500 }}>Confirm password</label>
            <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="Repeat password" required style={inp} />
          </div>
          <button type="submit" disabled={loading} style={{ width: "100%", padding: "12px", fontSize: 15, fontWeight: 600, background: loading ? "#ccc" : "#0071E3", color: "#fff", border: "none", borderRadius: 10, cursor: loading ? "default" : "pointer", fontFamily: "'DM Sans', sans-serif" }}>
            {loading ? "Resetting…" : "Reset password"}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── Inline Auth Modal ────────────────────────────────────────────────────────
function InlineAuthModal({ onClose, onSuccess }) {
  const [mode, setMode] = useState("login"); // login | register | forgot | reset_sent
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const inp = {
    width: "100%", boxSizing: "border-box", padding: "11px 14px",
    fontSize: 14, border: "1px solid #d0d0d8", borderRadius: 10,
    background: "#fff", color: "#1d1d1f",
    fontFamily: "'DM Sans', sans-serif", outline: "none", marginTop: 6,
  };

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true); setError(""); setSuccess("");
    try {
      if (mode === "forgot") {
        const res = await fetch(`${API}/auth/forgot-password`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: email.toLowerCase() }),
        });
        const data = await res.json();
        setSuccess(data.message);
        setMode("reset_sent");
        setLoading(false);
        return;
      }
      const endpoint = mode === "login" ? "/auth/login" : "/auth/register";
      const body = mode === "login"
        ? { email: email.toLowerCase(), password }
        : { email: email.toLowerCase(), password, full_name: name };
      const res = await fetch(`${API}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Something went wrong");
      localStorage.setItem("js_access_token", data.access_token);
      localStorage.setItem("js_refresh_token", data.refresh_token);
      localStorage.setItem("js_user", JSON.stringify(data.user));
      onSuccess(data.user);
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 9000, padding: 20 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: "#fff", borderRadius: 20, padding: "36px 32px", width: "100%", maxWidth: 400, boxShadow: "0 20px 60px rgba(0,0,0,0.2)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 24 }}>
          <div style={{ width: 30, height: 30, background: "#0071E3", borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14 }}>⚡</div>
          <span style={{ fontSize: 17, fontWeight: 700, color: "#1d1d1f" }}>JobStream</span>
        </div>
        {mode !== "reset_sent" && (
          <>
            <h2 style={{ fontSize: 22, fontWeight: 700, color: "#1d1d1f", marginBottom: 4, letterSpacing: -0.5 }}>
              {mode === "login" ? "Welcome back" : mode === "forgot" ? "Reset password" : "Create account"}
            </h2>
            <p style={{ fontSize: 13, color: "#888", marginBottom: 24 }}>
              {mode === "login" ? "Sign in to apply for jobs" : mode === "forgot" ? "Enter your email and we'll send a reset link" : "Join to start applying"}
            </p>
          </>
        )}
        {error && <div style={{ background: "#fff0f0", border: "1px solid #f5c6c6", borderRadius: 8, padding: "10px 14px", marginBottom: 16, fontSize: 13, color: "#c0392b" }}>{error}</div>}
        <form onSubmit={handleSubmit}>
          {mode === "register" && (
            <div style={{ marginBottom: 14 }}>
              <label style={{ fontSize: 11, color: "#666", textTransform: "uppercase", letterSpacing: "0.4px", fontWeight: 500 }}>Full name</label>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ada Okonkwo" required style={inp} />
            </div>
          )}
          <div style={{ marginBottom: 14 }}>
            <label style={{ fontSize: 11, color: "#666", textTransform: "uppercase", letterSpacing: "0.4px", fontWeight: 500 }}>Email</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@email.com" required style={inp} />
          </div>
          {mode !== "forgot" && (
            <div style={{ marginBottom: 20 }}>
              <label style={{ fontSize: 11, color: "#666", textTransform: "uppercase", letterSpacing: "0.4px", fontWeight: 500 }}>Password</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Min. 8 characters" required={mode !== "forgot"} style={inp} />
            </div>
          )}
          {mode === "login" && (
            <div style={{ textAlign: "right", marginBottom: 16, marginTop: -4 }}>
              <span onClick={() => { setMode("forgot"); setError(""); }} style={{ color: "#0071E3", cursor: "pointer", fontSize: 13 }}>Forgot password?</span>
            </div>
          )}
          <button type="submit" disabled={loading} style={{ width: "100%", padding: "12px", fontSize: 15, fontWeight: 600, background: loading ? "#ccc" : "#0071E3", color: "#fff", border: "none", borderRadius: 10, cursor: loading ? "default" : "pointer", fontFamily: "'DM Sans', sans-serif" }}>
            {loading ? "Please wait…" : mode === "login" ? "Sign in" : mode === "forgot" ? "Send reset link" : "Create account"}
          </button>
        </form>
        {mode === "reset_sent" ? (
          <div style={{ textAlign: "center", padding: "16px 0" }}>
            <div style={{ fontSize: 32, marginBottom: 12 }}>📧</div>
            <p style={{ fontSize: 14, color: "#1d1d1f", fontWeight: 500, marginBottom: 8 }}>Check your email</p>
            <p style={{ fontSize: 13, color: "#888", marginBottom: 20 }}>We sent a reset link to <strong>{email}</strong></p>
            <span onClick={() => { setMode("login"); setError(""); setSuccess(""); }} style={{ color: "#0071E3", cursor: "pointer", fontSize: 13, fontWeight: 500 }}>Back to sign in</span>
          </div>
        ) : (
          <>
    
            <p style={{ textAlign: "center", marginTop: 18, fontSize: 13, color: "#888" }}>
              {mode === "forgot" ? (
                <span onClick={() => { setMode("login"); setError(""); }} style={{ color: "#0071E3", cursor: "pointer", fontWeight: 500 }}>← Back to sign in</span>
              ) : mode === "login" ? (
                <>No account? <span onClick={() => { setMode("register"); setError(""); }} style={{ color: "#0071E3", cursor: "pointer", fontWeight: 500 }}>Create one</span></>
              ) : (
                <>Have an account? <span onClick={() => { setMode("login"); setError(""); }} style={{ color: "#0071E3", cursor: "pointer", fontWeight: 500 }}>Sign in</span></>
              )}
            </p>
          </>
        )}
      </div>
    </div>
  );
}

function ApplyModal({ job, onClose, onSuccess, user }) {
  const [form, setForm] = useState({
    name: user?.full_name || "",
    email: user?.email || "",
    phone: "",
    resume_url: "",
    cover_note: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit() {
    if (!form.name || !form.email) { setError("Name and email are required."); return; }
    setLoading(true); setError("");
    try {
      await api(`/jobs/${job.id}/apply`, { method: "POST", body: JSON.stringify(form) });
      onSuccess("Application submitted!");
      onClose();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  const inp = { width: "100%", boxSizing: "border-box", background: "#fff", border: "1px solid #d0d0d8", borderRadius: 8, padding: "10px 12px", fontSize: 13, color: "#1d1d1f", fontFamily: "'DM Sans', sans-serif", outline: "none" };

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 200, padding: 20 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: "#fff", border: "1px solid #e0e0e8", borderRadius: 16, width: "100%", maxWidth: 480, maxHeight: "90vh", overflowY: "auto" }}>
        <div style={{ padding: "22px 24px 16px", borderBottom: "1px solid #e8e8f0", display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 600, color: "#1d1d1f" }}>{job.title}</div>
            <div style={{ fontSize: 12, color: "#888", marginTop: 3 }}>{job.company} · {job.location}</div>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", color: "#888", fontSize: 20, cursor: "pointer" }}>✕</button>
        </div>
        <div style={{ padding: "20px 24px" }}>
          {error && <div style={{ background: "#fff0f0", border: "1px solid #f5c6c6", borderRadius: 8, padding: "10px 14px", fontSize: 13, color: "#c0392b", marginBottom: 16 }}>{error}</div>}
          {[
            { key: "name", label: "Full name *", placeholder: "Ada Okonkwo", type: "text" },
            { key: "email", label: "Email *", placeholder: "ada@email.com", type: "email" },
            { key: "phone", label: "Phone", placeholder: "+234 800 000 0000", type: "tel" },
            { key: "resume_url", label: "Resume / CV link", placeholder: "https://linkedin.com/in/…", type: "text" },
          ].map(({ key, label, placeholder, type }) => (
            <div key={key} style={{ marginBottom: 14 }}>
              <label style={{ fontSize: 11, color: "#666", display: "block", marginBottom: 5, textTransform: "uppercase", letterSpacing: "0.5px" }}>{label}</label>
              <input type={type} value={form[key]} onChange={set(key)} placeholder={placeholder} style={inp} />
            </div>
          ))}
          <div style={{ marginBottom: 14 }}>
            <label style={{ fontSize: 11, color: "#666", display: "block", marginBottom: 5, textTransform: "uppercase", letterSpacing: "0.5px" }}>Cover note</label>
            <textarea value={form.cover_note} onChange={set("cover_note")} placeholder="Why are you a great fit?" style={{ ...inp, height: 90, resize: "vertical" }} />
          </div>
        </div>
        <div style={{ padding: "16px 24px", borderTop: "1px solid #e8e8f0", display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button onClick={onClose} style={{ background: "none", border: "1px solid #d0d0d8", borderRadius: 8, padding: "8px 16px", fontSize: 13, color: "#666", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>Cancel</button>
          <button onClick={submit} disabled={loading} style={{ background: "#0071E3", border: "none", borderRadius: 8, padding: "8px 20px", fontSize: 13, fontWeight: 500, color: "#fff", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", opacity: loading ? 0.6 : 1 }}>
            {loading ? "Submitting…" : "Submit →"}
          </button>
        </div>
      </div>
    </div>
  );
}

function JobsPage({ onApply, toast, isDark = true, user, onAuthRequired }) {
  const [jobs, setJobs] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expandedId, setExpandedId] = useState(null);
  const [search, setSearch] = useState("");
  const [jobType, setJobType] = useState("");
  const [dept, setDept] = useState("");
  const [scraping, setScraping] = useState(false);
  const [backfilling, setBackfilling] = useState(false);
  const debounceRef = useRef(null);

  const load = useCallback(async (q = search, t = jobType, d = dept) => {
    setLoading(true); setError("");
    try {
      const params = new URLSearchParams({ search: q, job_type: t, department: d, limit: 100 });
      const data = await api(`/jobs?${params}`);
      setJobs(data.jobs); setTotal(data.total);
    } catch (e) {
      setError("Cannot reach API at " + API + ". Is the backend running?");
    } finally { setLoading(false); }
  }, [search, jobType, dept]);

  useEffect(() => { load("", "", ""); }, []);

  function onSearch(v) {
    setSearch(v);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => load(v, jobType, dept), 350);
  }

  async function triggerScrape() {
    setScraping(true);
    try {
      await api("/scrape", { method: "POST" });
      toast("Scrape started! Jobs will appear shortly.");
      setTimeout(() => load(search, jobType, dept), 5000);
    } catch { toast("Could not reach scraper API."); }
    finally { setScraping(false); }
  }

  async function backfillDescriptions() {
    setBackfilling(true);
    try {
      await api("/scrape/backfill-descriptions", { method: "POST" });
      toast("Fetching descriptions in background — refresh in a few minutes.");
    } catch { toast("Failed to start backfill."); }
    finally { setBackfilling(false); }
  }


  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 600, color: "#f0f0f2", letterSpacing: -0.5 }}>Job Board</div>
          <div style={{ fontSize: 13, color: "#555", marginTop: 3 }}>{total} live jobs</div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={backfillDescriptions} disabled={backfilling} style={{
            background: backfilling ? "#1e1e24" : "transparent", border: "1px solid #3a3a42",
            borderRadius: 9, padding: "8px 16px", fontSize: 12, color: backfilling ? "#666" : "#888",
            cursor: backfilling ? "default" : "pointer", fontFamily: "'DM Sans', sans-serif",
          }}>
            {backfilling ? "Fetching descriptions…" : "📄 Fetch all descriptions"}
          </button>
          <button onClick={triggerScrape} disabled={scraping} style={{
            background: scraping ? "#1e1e24" : "#0071E3", border: "1px solid #3a3a42",
            borderRadius: 9, padding: "8px 16px", fontSize: 12, color: scraping ? "#666" : "#fff",
            cursor: scraping ? "default" : "pointer", fontFamily: "'DM Sans', sans-serif", display: "flex", alignItems: "center", gap: 6,
          }}>
            {scraping ? "Streaming…" : "⟳ Stream now"}
          </button>
        </div>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: 10, marginBottom: 20, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 200, position: "relative" }}>
          <span style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", color: "#555", fontSize: 14 }}>🔍</span>
          <input value={search} onChange={(e) => onSearch(e.target.value)} placeholder="Search roles, companies…"
            style={{ width: "100%", boxSizing: "border-box", background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 9, padding: "9px 12px 9px 34px", fontSize: 13, color: isDark ? "#f0f0f2" : "#1a1a1a", fontFamily: "'DM Sans', sans-serif", outline: "none" }}
          />
        </div>
        {[
          { val: jobType, set: (v) => { setJobType(v); load(search, v, dept); }, opts: ["", "Full-time", "Part-time", "Contract", "Remote"], label: "Type" },
          { val: dept, set: (v) => { setDept(v); load(search, jobType, v); }, opts: ["", "Engineering", "Design", "Marketing", "Product", "Operations"], label: "Department" },
        ].map(({ val, set, opts, label }) => (
          <select key={label} value={val} onChange={(e) => set(e.target.value)}
            style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 9, padding: "9px 12px", fontSize: 13, color: val ? (isDark ? "#f0f0f2" : "#1a1a1a") : (isDark ? "#666" : "#999"), fontFamily: "'DM Sans', sans-serif", outline: "none", cursor: "pointer", colorScheme: isDark ? "dark" : "light" }}>
            {opts.map((o) => <option key={o} value={o}>{o || `All ${label}s`}</option>)}
          </select>
        ))}
      </div>

      {error && (
        <div style={{ background: isDark ? "rgba(245,101,101,0.08)" : "rgba(245,101,101,0.05)", border: "1px solid rgba(245,101,101,0.25)", borderRadius: 10, padding: "16px 20px", marginBottom: 20 }}>
          <div style={{ color: "#f87171", fontSize: 14, fontWeight: 500, marginBottom: 6 }}>Backend not connected</div>
          <div style={{ color: "#888", fontSize: 12 }}>{error}</div>
          <div style={{ color: "#555", fontSize: 11, marginTop: 8, fontFamily: "'DM Mono', monospace" }}>
            Run: <span style={{ color: "#0071E3" }}>uvicorn main:app --reload --port 8000</span>
          </div>
        </div>
      )}

      {loading ? <Spinner /> : jobs.length === 0 ? (
        <div style={{ textAlign: "center", padding: "60px 0", color: "#444" }}>
          <div style={{ fontSize: 36, marginBottom: 12 }}>📭</div>
          <div style={{ fontSize: 15, color: "#666", marginBottom: 6 }}>No jobs found</div>
          <div style={{ fontSize: 12 }}>Try running a scrape or adjusting your filters</div>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {jobs.map((j) => <JobCard key={j.id} job={j} onApply={onApply} onView={(job) => setExpandedId(expandedId === job.id ? null : job.id)} isExpanded={expandedId === j.id} isDark={isDark} user={user} onAuthRequired={onAuthRequired} />)}
        </div>
      )}
    </div>
  );
}

function ScraperPage({ toast, isDark = true }) {
  const [companies, setCompanies] = useState([]);
  const [history, setHistory] = useState([]);
  const [newName, setNewName] = useState("");
  const [newUrl, setNewUrl] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState(null); // company id currently being scraped

  async function load() {
    try {
      const [c, h] = await Promise.all([api("/companies"), api("/scrape/history")]);
      setCompanies(c);
      setHistory(h);
    } catch {}
    finally { setLoading(false); }
  }

  useEffect(() => { load(); }, []);

  async function addCompany() {
    if (!newName || !newUrl) return;
    try {
      await api("/companies", { method: "POST", body: JSON.stringify({ name: newName, url: newUrl }) });
      setNewName(""); setNewUrl("");
      load();
      toast(`Added ${newName}`);
    } catch (e) { toast("Failed: " + e.message); }
  }

  async function removeCompany(id, name) {
    await api(`/companies/${id}`, { method: "DELETE" });
    load();
    toast(`Removed ${name}`);
  }

  async function scrapeOne(id, name) {
    setBusyId(id);
    try {
      await api(`/scrape/${id}`, { method: "POST" });
      toast(`Scraping ${name}... jobs will appear shortly.`);
      setTimeout(load, 6000);
    } catch (e) {
      toast(`Scrape failed: ${e.message}`);
    } finally {
      setBusyId(null);
    }
  }

  async function forceOne(id, name) {
    setBusyId(id);
    try {
      const res = await fetch(`${API}/scrape/${id}/force`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (!res.ok) {
        const txt = await res.text();
        toast(`Error ${res.status}: ${txt}`);
        return;
      }
      toast(`Force rescraping ${name}... refresh in 30 seconds.`);
      setTimeout(load, 15000);
    } catch (e) {
      toast(`Network error: ${e.message}`);
    } finally {
      setBusyId(null);
    }
  }

  const inp = {
    background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 8,
    padding: "9px 12px", fontSize: 13, color: isDark ? "#f0f0f2" : "#1a1a1a",
    fontFamily: "'DM Sans', sans-serif", outline: "none",
  };

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 22, fontWeight: 600, color: "#f0f0f2", letterSpacing: -0.5 }}>Streamer Config</div>
        <div style={{ fontSize: 13, color: "#555", marginTop: 3 }}>Manage career pages to stream automatically</div>
      </div>

      {/* Companies list */}
      <div style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "20px 22px", marginBottom: 16 }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: isDark ? "#f0f0f2" : "#1a1a1a", marginBottom: 16 }}>Tracked companies</div>

        {loading ? <Spinner /> : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 16 }}>
            {companies.map((c) => (
              <div key={c.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 14px", background: isDark ? "#1C1C20" : "#f8f8fb", borderRadius: 8, border: isDark ? "1px solid #2a2a32" : "1px solid #e8e8f0" }}>
                {/* Logo */}
                <CompanyLogo name={c.name} sourceUrl={c.url} size={28} />
                {/* Name + URL */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, color: isDark ? "#f0f0f2" : "#1a1a1a" }}>{c.name}</div>
                  <div style={{ fontSize: 10, color: isDark ? "#555" : "#888", fontFamily: "'DM Mono', monospace", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.url}</div>
                </div>
                {/* Scrape button */}
                <button
                  onClick={() => scrapeOne(c.id, c.name)}
                  disabled={busyId === c.id}
                  style={{ background: "rgba(0,113,227,0.1)", border: "1px solid rgba(123,110,246,0.3)", borderRadius: 6, padding: "4px 10px", fontSize: 11, color: busyId === c.id ? "#555" : "#4DA3FF", cursor: busyId === c.id ? "default" : "pointer", fontFamily: "'DM Sans', sans-serif", whiteSpace: "nowrap" }}
                >
                  {busyId === c.id ? "Streaming..." : "⟳ Stream"}
                </button>
                {/* Force rescrape button */}
                <button
                  onClick={() => forceOne(c.id, c.name)}
                  disabled={busyId === c.id}
                  style={{ background: "rgba(245,101,101,0.1)", border: "1px solid rgba(245,101,101,0.3)", borderRadius: 6, padding: "4px 10px", fontSize: 11, color: busyId === c.id ? "#555" : "#f87171", cursor: busyId === c.id ? "default" : "pointer", fontFamily: "'DM Sans', sans-serif", whiteSpace: "nowrap" }}
                >
                  ↺ Force
                </button>
                {/* Remove button */}
                <button
                  onClick={() => removeCompany(c.id, c.name)}
                  style={{ background: "none", border: "none", color: "#555", cursor: "pointer", fontSize: 16, lineHeight: 1, padding: 4 }}
                  onMouseEnter={(e) => e.currentTarget.style.color = "#f87171"}
                  onMouseLeave={(e) => e.currentTarget.style.color = "#555"}
                >✕</button>
              </div>
            ))}
          </div>
        )}

        {/* Add company form */}
        <div style={{ display: "flex", gap: 8 }}>
          <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Company name" style={{ ...inp, width: 140 }} />
          <input value={newUrl} onChange={(e) => setNewUrl(e.target.value)} placeholder="https://company.com/careers" style={{ ...inp, flex: 1 }} />
          <button onClick={addCompany} style={{ background: "#0071E3", border: "none", borderRadius: 8, padding: "9px 16px", fontSize: 13, color: "#fff", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>+ Add</button>
        </div>
      </div>

      {/* Scrape history */}
      <div style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "20px 22px" }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: isDark ? "#f0f0f2" : "#1a1a1a", marginBottom: 16 }}>Scrape history</div>
        {history.length === 0 ? (
          <div style={{ color: "#444", fontSize: 12, fontFamily: "'DM Mono', monospace" }}>No scrape runs yet.</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {history.map((r) => (
              <div key={r.id} style={{ display: "flex", gap: 12, alignItems: "center", padding: "8px 0", borderBottom: isDark ? "1px solid #1e1e24" : "1px solid #ebebf0", fontSize: 12 }}>
                <Chip variant={r.status === "success" ? "green" : r.status === "running" ? "accent" : "red"}>{r.status}</Chip>
                <span style={{ color: isDark ? "#888" : "#555", fontFamily: "'DM Mono', monospace", flex: 1 }}>{new Date(r.started_at).toLocaleString()}</span>
                <span style={{ color: isDark ? "#555" : "#888" }}>{r.jobs_found} found · <span style={{ color: "#3DD68C" }}>+{r.jobs_new} new</span></span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}


function ApplicationsPage({ isDark = true }) {
  const [apps, setApps] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api("/applications").then(setApps).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const statusVariant = { new: "accent", reviewing: "amber", interview: "green", offered: "green", rejected: "red" };

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 22, fontWeight: 600, color: "#f0f0f2", letterSpacing: -0.5 }}>Applications</div>
        <div style={{ fontSize: 13, color: "#555", marginTop: 3 }}>{apps.length} total submissions</div>
      </div>
      {loading ? <Spinner /> : apps.length === 0 ? (
        <div style={{ textAlign: "center", padding: "60px 0", color: "#444" }}>
          <div style={{ fontSize: 36, marginBottom: 12 }}>📋</div>
          <div style={{ fontSize: 15, color: "#666" }}>No applications yet</div>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {apps.map((a) => (
            <div key={a.id} style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 12, padding: "16px 18px", display: "flex", gap: 14, alignItems: "flex-start" }}>
              <CompanyLogo name={a.company || a.name} size={36} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
                  <span style={{ fontSize: 14, fontWeight: 500, color: isDark ? "#f0f0f2" : "#1a1a1a" }}>{a.name}</span>
                  <Chip variant={statusVariant[a.status] || "default"}>{a.status}</Chip>
                </div>
                <div style={{ fontSize: 12, color: "#666" }}>{a.email}</div>
                <div style={{ fontSize: 11, color: "#444", marginTop: 4, fontFamily: "'DM Mono', monospace" }}>
                  {a.job_title} · {new Date(a.submitted_at).toLocaleDateString()}
                </div>
              </div>
              {a.resume_url && (
                <a href={a.resume_url} target="_blank" rel="noreferrer" style={{ fontSize: 11, color: "#0071E3", textDecoration: "none", whiteSpace: "nowrap" }}>Resume →</a>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Stats bar ─────────────────────────────────────────────────────────────────
function StatsBar({ isDark = true }) {
  const [stats, setStats] = useState({ jobs: 0, companies: 0, apps: 0, lastRun: null });

  useEffect(() => {
    Promise.all([
      api("/jobs?limit=1").catch(() => ({ total: 0 })),
      api("/companies").catch(() => []),
      api("/applications").catch(() => []),
      api("/scrape/status").catch(() => ({})),
    ]).then(([j, c, a, s]) => {
      setStats({
        jobs: j.total || 0,
        companies: c.length || 0,
        apps: a.length || 0,
        lastRun: s.last_run?.finished_at ? new Date(s.last_run.finished_at).toLocaleTimeString() : null,
      });
    });
  }, []);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: 24 }}>
      {[
        { label: "Active jobs", val: stats.jobs },
        { label: "Companies", val: stats.companies },
        { label: "Applications", val: stats.apps },
        { label: "Last scraped", val: stats.lastRun || "—" },
      ].map(({ label, val }) => (
        <div key={label} style={{ background: isDark ? "#141416" : "#ffffff", border: (isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8"), borderRadius: 12, padding: "14px 16px", transition: "background 0.2s" }}>
          <div style={{ fontSize: typeof val === "number" ? 24 : 15, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1a1a1a", letterSpacing: -0.5 }}>{val}</div>
          <div style={{ fontSize: 11, color: isDark ? "#555" : "#888", marginTop: 4 }}>{label}</div>
        </div>
      ))}
    </div>
  );
}


// ── Nav Item ─────────────────────────────────────────────────────────────────
// ── Tiny components ─────────────────────────────────────────────────────────
function Spinner() {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 48 }}>
      <div style={{ width: 28, height: 28, border: "2px solid #e0e0e8", borderTopColor: "#0071E3", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
    </div>
  );
}

function Chip({ children, variant = "default", isDark = true }) {
  const styles = {
    default: { background: isDark ? "#1e1e24" : "#efefef", color: isDark ? "#888" : "#444", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d0" },
    accent:  { background: "rgba(0,113,227,0.1)", color: "#0071E3", border: "1px solid rgba(0,113,227,0.2)" },
    green:   { background: "rgba(61,214,140,0.1)", color: "#3DD68C", border: "1px solid rgba(61,214,140,0.2)" },
    amber:   { background: "rgba(245,166,35,0.1)", color: "#F5A623", border: "1px solid rgba(245,166,35,0.2)" },
    red:     { background: "rgba(245,101,101,0.1)", color: "#f87171", border: "1px solid rgba(245,101,101,0.2)" },
  };
  return (
    <span style={{ ...styles[variant], fontSize: 11, padding: "2px 9px", borderRadius: 20, fontFamily: "'DM Mono', monospace", whiteSpace: "nowrap" }}>
      {children}
    </span>
  );
}

function Toast({ msg, onClose }) {
  useEffect(() => { const t = setTimeout(onClose, 3500); return () => clearTimeout(t); }, [onClose]);
  return (
    <div style={{ position: "fixed", bottom: 24, right: 24, zIndex: 9999, background: "#1d1d1f", border: "1px solid #3DD68C", color: "#3DD68C", padding: "12px 20px", borderRadius: 10, fontSize: 13, fontFamily: "'DM Sans', sans-serif", boxShadow: "0 4px 24px rgba(0,0,0,0.3)", animation: "slideUp 0.25s ease" }}>
      ✓ {msg}
    </div>
  );
}

function NavItem({ icon, label, active, sidebarOpen, isDark, onClick }) {
  return (
    <button
      onClick={onClick}
      title={!sidebarOpen ? label : ""}
      style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: sidebarOpen ? "9px 12px" : "10px",
        width: "100%", borderRadius: 9, border: "none", cursor: "pointer", fontSize: 13,
        fontFamily: "'DM Sans', sans-serif", transition: "all 0.15s",
        background: active ? "rgba(0,113,227,0.1)" : "none",
        color: active ? "#0071E3" : (isDark ? "#777" : "#555"),
        justifyContent: sidebarOpen ? "flex-start" : "center",
      }}
    >
      <span style={{ fontSize: 17, flexShrink: 0, lineHeight: 1 }}>{icon}</span>
      {sidebarOpen && <span style={{ marginLeft: 2 }}>{label}</span>}
    </button>
  );
}


// ── App Shell ─────────────────────────────────────────────────────────────────
export default function App() {
  const [page, setPage] = useState("jobs");
  const [applyJob, setApplyJob] = useState(null);
  const [toast, setToast] = useState("");
  const [theme, setTheme] = useState("light");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [user, setUser] = useState(getStoredUser());
  const [showAuth, setShowAuth] = useState(false);
  const [resetToken, setResetToken] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("token") || "";
  });
  const isDark = theme === "dark";

  const showToast = (msg) => { setToast(msg); };

  async function handleLogout() {
    const rt = localStorage.getItem("js_refresh_token");
    if (rt) await apiLogout(rt);
    clearAuth();
    setUser(null);
    showToast("Signed out successfully");
  }

  const NAV = [
    { id: "jobs", icon: "💼", label: "Job Board" },
    { id: "scraper", icon: "🤖", label: "Streamer" },
    { id: "applications", icon: "📋", label: "Applications" },
  ];

  return (
    <div style={{ display: "grid", gridTemplateColumns: sidebarOpen ? "220px 1fr" : "52px 1fr", minHeight: "100vh", fontFamily: "'DM Sans', sans-serif", background: isDark ? "#0D0D0F" : "#f4f4f6", color: isDark ? "#f0f0f2" : "#1a1a1a", transition: "all 0.25s ease" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes slideUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        .nav-item-wrap { overflow: visible !important; }
        .nav-item-wrap:hover .nav-tooltip { opacity: 1 !important; }
        aside { overflow: visible !important; }
        input::placeholder, textarea::placeholder { color: #444; }
        ::-webkit-scrollbar { width: 6px; } ::-webkit-scrollbar-track { background: transparent; } ::-webkit-scrollbar-thumb { background: #2a2a32; border-radius: 3px; }
        select option { background: ${isDark ? "#141416" : "#ffffff"}; color: ${isDark ? "#f0f0f2" : "#111111"}; }
        select { color-scheme: ${isDark ? "dark" : "light"}; }
      `}</style>

      {/* Sidebar */}
      <aside style={{ background: isDark ? "#0f0f12" : "#ffffff", borderRight: isDark ? "1px solid #1e1e24" : "1px solid #e0e0e8", padding: sidebarOpen ? "20px 14px" : "12px 8px", display: "flex", flexDirection: "column", gap: 4, position: "sticky", top: 0, height: "100vh", transition: "all 0.25s ease", overflow: "hidden", width: sidebarOpen ? "220px" : "52px", minWidth: sidebarOpen ? "220px" : "52px" }}>

        {/* Header: logo + name + burger */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20, gap: 8 }}>
          {/* Logo + Name */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, overflow: "hidden", flex: 1, minWidth: 0 }}>
            <div style={{ width: 28, height: 28, background: "#0071E3", borderRadius: 7, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, flexShrink: 0 }}>⚡</div>
            {sidebarOpen && (
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1a1a1a", letterSpacing: -0.3, whiteSpace: "nowrap" }}>JobStream</div>
              </div>
            )}
          </div>
          {/* Burger button */}
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            title={sidebarOpen ? "Collapse menu" : "Expand menu"}
            style={{ background: "none", border: "none", cursor: "pointer", padding: 4, flexShrink: 0, display: "flex", flexDirection: "column", gap: 3, alignItems: "center", justifyContent: "center" }}
          >
            <span style={{ display: "block", width: 16, height: 2, background: isDark ? "#666" : "#999", borderRadius: 2 }} />
            <span style={{ display: "block", width: 16, height: 2, background: isDark ? "#666" : "#999", borderRadius: 2 }} />
            <span style={{ display: "block", width: 16, height: 2, background: isDark ? "#666" : "#999", borderRadius: 2 }} />
          </button>
        </div>

        {/* Theme toggle - visible only when expanded */}
        {sidebarOpen && (
          <button
            onClick={() => setTheme(isDark ? "light" : "dark")}
            title={isDark ? "Switch to light mode" : "Switch to dark mode"}
            style={{ background: isDark ? "#1C1C20" : "#e8e8ec", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 20, padding: "4px 12px", fontSize: 11, color: isDark ? "#888" : "#555", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", display: "flex", alignItems: "center", gap: 6, marginBottom: 8, alignSelf: "flex-end" }}
          >
            {isDark ? "☀ Light" : "● Dark"}
          </button>
        )}

        {/* Nav items */}
        {NAV.map(({ id, icon, label }) => (
          <NavItem
            key={id}
            id={id}
            icon={icon}
            label={label}
            active={page === id}
            sidebarOpen={sidebarOpen}
            isDark={isDark}
            onClick={() => setPage(id)}
          />
        ))}

        {/* Auth section */}
        <div style={{ borderTop: isDark ? "1px solid #1e1e24" : "1px solid #e8e8f0", paddingTop: 12, marginTop: 8 }}>
          {user ? (
            <div>
              {sidebarOpen && (
                <div style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: isDark ? "#e0e0e0" : "#1d1d1f", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {user.full_name}
                  </div>
                  <div style={{ fontSize: 10, color: isDark ? "#666" : "#999", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {user.email}
                  </div>
                </div>
              )}
              <button
                onClick={handleLogout}
                title="Sign out"
                style={{ width: "100%", padding: sidebarOpen ? "8px 12px" : "8px", background: "none", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 8, fontSize: 12, color: isDark ? "#888" : "#666", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", display: "flex", alignItems: "center", justifyContent: sidebarOpen ? "flex-start" : "center", gap: 6 }}
              >
                <span>↪</span>
                {sidebarOpen && <span>Sign out</span>}
              </button>
            </div>
          ) : (
            <button
              onClick={() => setShowAuth(true)}
              title="Sign in"
              style={{ width: "100%", padding: sidebarOpen ? "9px 12px" : "9px", background: "#0071E3", border: "none", borderRadius: 8, fontSize: 13, fontWeight: 500, color: "#fff", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", display: "flex", alignItems: "center", justifyContent: sidebarOpen ? "flex-start" : "center", gap: 6 }}
            >
              <span>👤</span>
              {sidebarOpen && <span>Sign in</span>}
            </button>
          )}
        </div>

        {/* Streamer active status */}
        <div style={{ marginTop: "auto", background: isDark ? "#141416" : "#f0f0f4", border: isDark ? "1px solid #1e1e24" : "1px solid #d8d8e0", borderRadius: 10, padding: sidebarOpen ? "12px 14px" : "10px 6px", display: "flex", flexDirection: "column", alignItems: sidebarOpen ? "flex-start" : "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 8, height: 8, background: "#3DD68C", borderRadius: "50%", display: "inline-block", flexShrink: 0, boxShadow: "0 0 6px #3DD68C" }} />
            {sidebarOpen && <span style={{ fontSize: 12, fontWeight: 500, color: isDark ? "#e0e0e0" : "#222" }}>Streamer active</span>}
          </div>
          {sidebarOpen && <div style={{ fontSize: 10, color: isDark ? "#aaa" : "#666", fontFamily: "'DM Mono', monospace", marginTop: 4 }}>Streams every 2 hours</div>}
        </div>
        {sidebarOpen && (
          <div style={{ textAlign: "center", fontSize: 9, color: isDark ? "#333" : "#bbb", fontFamily: "'DM Mono', monospace", marginTop: 8, letterSpacing: "0.5px" }}>MVP v0.1</div>
        )}
      </aside>

      {/* Main */}
      <main style={{ padding: "28px 32px", overflowY: "auto", maxHeight: "100vh", background: isDark ? "#0D0D0F" : "#f4f4f6", transition: "background 0.2s", position: "relative" }}>

        <StatsBar isDark={isDark} />
        {page === "jobs" && <JobsPage onApply={setApplyJob} toast={showToast} isDark={isDark} user={user} onAuthRequired={() => setShowAuth(true)} />}
        {page === "scraper" && <ScraperPage toast={showToast} isDark={isDark} />}
        {page === "applications" && <ApplicationsPage isDark={isDark} />}
      </main>

      {applyJob && <ApplyModal job={applyJob} onClose={() => setApplyJob(null)} onSuccess={showToast} user={user} />}
      {showAuth && <InlineAuthModal onClose={() => setShowAuth(false)} onSuccess={(u) => { setUser(u); showToast(`Welcome, ${u.full_name}!`); }} />}
      {resetToken && <ResetPasswordModal token={resetToken} onClose={() => { setResetToken(""); window.history.replaceState({}, "", "/"); }} onSuccess={() => { setResetToken(""); window.history.replaceState({}, "", "/"); showToast("Password reset! Please sign in."); setShowAuth(true); }} />}
      {toast && <Toast msg={toast} onClose={() => setToast("")} />}
    </div>
  );
}
