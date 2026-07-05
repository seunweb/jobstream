import { useState, useEffect, useCallback, useRef } from "react";
// Auth helpers - safe inline implementation
function getStoredUser() { try { return JSON.parse(localStorage.getItem("js_user")); } catch { return null; } }
function getAccessToken() { return localStorage.getItem("js_access_token"); }
function clearAuth() { ["js_access_token","js_refresh_token","js_user"].forEach(k => localStorage.removeItem(k)); }
async function apiLogout(rt) { try { await fetch(`${API}/auth/logout`, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({refresh_token: rt}) }); } catch {} }

// ── Config ──────────────────────────────────────────────────────────────────
const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

function slugify(text) {
  return (text || "").toLowerCase().trim()
    .replace(/[^\w\s-]/g, "").replace(/[\s_]+/g, "-")
    .replace(/-+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80);
}
function makeJobSlug(title, company, id) {
  return `${slugify(title)}-${slugify(company)}-${id}`;
}
function makeOrgSlug(name) {
  return slugify(name);
}

async function api(path, opts = {}) {
  const token = getAccessToken();
  const headers = { "Content-Type": "application/json", ...opts.headers };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${API}${path}`, { ...opts, headers });

  if (res.status === 401) {
    // Try to refresh the token before giving up
    const rt = localStorage.getItem("js_refresh_token");
    if (rt) {
      try {
        const refreshRes = await fetch(`${API}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: rt }),
        });
        if (refreshRes.ok) {
          const data = await refreshRes.json();
          localStorage.setItem("js_access_token", data.access_token);
          if (data.refresh_token) localStorage.setItem("js_refresh_token", data.refresh_token);
          // Retry the original request with the new token
          headers["Authorization"] = `Bearer ${data.access_token}`;
          const retry = await fetch(`${API}${path}`, { ...opts, headers });
          if (retry.ok) {
            if (retry.status === 204) return null;
            return retry.json();
          }
        }
      } catch {}
    }
    // Refresh failed — clear auth and reload
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

// ── Utility Components ─────────────────────────────────────────────────────
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
    purple:  { background: "rgba(155,89,182,0.1)", color: "#9B59B6", border: "1px solid rgba(155,89,182,0.2)" },
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

function StatCard({ label, value, sub, color = "#0071E3", isDark }) {
  return (
    <div style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "20px 22px", flex: 1, minWidth: 140 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: isDark ? "#666" : "#999", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 8 }}>{label}</div>
      <div style={{ fontSize: 28, fontWeight: 700, color: color, letterSpacing: -1, marginBottom: 4 }}>{value ?? "—"}</div>
      {sub && <div style={{ fontSize: 11, color: isDark ? "#555" : "#aaa" }}>{sub}</div>}
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

function UserMenu({ user, onLogout, isDark, setPage }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    function handleClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const initial = (user.full_name || user.email || "?")[0].toUpperCase();

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          display: "flex", alignItems: "center", gap: 8,
          background: isDark ? "#1C1C20" : "#ffffff",
          border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8",
          borderRadius: 20, padding: "5px 12px 5px 6px",
          cursor: "pointer", fontFamily: "'DM Sans', sans-serif",
        }}
      >
        <div style={{
          width: 26, height: 26, borderRadius: "50%",
          background: "var(--btn-primary)", color: "#fff",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 12, fontWeight: 700, flexShrink: 0,
        }}>{initial}</div>
        <span style={{ fontSize: 13, fontWeight: 500, color: isDark ? "#e0e0e0" : "#1d1d1f" }}>
          {user.full_name?.split(" ")[0] || "Account"}
        </span>
        <span style={{ fontSize: 10, color: isDark ? "#666" : "#999" }}>{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div style={{
          position: "absolute", top: "calc(100% + 8px)", right: 0,
          background: isDark ? "#1C1C20" : "#ffffff",
          border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8",
          borderRadius: 12, minWidth: 200,
          boxShadow: "0 8px 32px rgba(0,0,0,0.15)",
          zIndex: 999, overflow: "hidden",
        }}>
          <div style={{ padding: "14px 16px", borderBottom: isDark ? "1px solid #2a2a32" : "1px solid #e8e8f0" }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 2 }}>{user.full_name}</div>
            <div style={{ fontSize: 11, color: isDark ? "#666" : "#999" }}>{user.email}</div>
            <div style={{ fontSize: 10, color: "#0071E3", marginTop: 4, textTransform: "capitalize" }}>{user.role}</div>
          </div>
          <div style={{ padding: "6px 0" }}>
            {[
              { icon: "👤", label: "My Profile",      page: "profile" },
              { icon: "📨", label: "My Applications", page: "myapps"  },
              { icon: "🔖", label: "Saved Jobs",       page: "saved"   },
              { icon: "🔔", label: "My Alerts",        page: "myalerts" },
              { icon: "➕", label: "Post a Job",       page: "postjob"  },
            ].map(({ icon, label, page }) => (
              <button key={label} onClick={() => { setOpen(false); setPage && setPage(page); }} style={{
                display: "flex", alignItems: "center", gap: 10,
                width: "100%", padding: "9px 16px",
                background: "none", border: "none", cursor: "pointer",
                fontSize: 13, color: isDark ? "#ccc" : "#333",
                fontFamily: "'DM Sans', sans-serif", textAlign: "left",
              }}
                onMouseEnter={(e) => e.currentTarget.style.background = isDark ? "#2a2a32" : "#f5f5f8"}
                onMouseLeave={(e) => e.currentTarget.style.background = "none"}
              >
                <span>{icon}</span> {label}
              </button>
            ))}
          </div>
          <div style={{ padding: "6px 0", borderTop: isDark ? "1px solid #2a2a32" : "1px solid #e8e8f0" }}>
            <button onClick={() => { setOpen(false); onLogout(); }} style={{
              display: "flex", alignItems: "center", gap: 10,
              width: "100%", padding: "9px 16px",
              background: "none", border: "none", cursor: "pointer",
              fontSize: 13, color: "#f87171",
              fontFamily: "'DM Sans', sans-serif", textAlign: "left",
            }}
              onMouseEnter={(e) => e.currentTarget.style.background = isDark ? "#2a2a32" : "#fff0f0"}
              onMouseLeave={(e) => e.currentTarget.style.background = "none"}
            >
              <span>↪</span> Sign out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

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
        { label: "Active jobs",   val: stats.jobs      },
        { label: "Companies",     val: stats.companies },
        { label: "Applications",  val: stats.apps      },
        { label: "Last streamed",  val: stats.lastRun || "—" },
      ].map(({ label, val }) => (
        <div key={label} style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 12, padding: "14px 16px" }}>
          <div style={{ fontSize: typeof val === "number" ? 24 : 15, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1a1a1a", letterSpacing: -0.5 }}>{val}</div>
          <div style={{ fontSize: 11, color: isDark ? "#555" : "#888", marginTop: 4 }}>{label}</div>
        </div>
      ))}
    </div>
  );
}











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
  "t2mobile":    "https://www.t2mobile.com.ng/_next/static/media/logos.1d851e63.png",
  "mtn":         "https://www.mtn.com/wp-content/themes/mtn-refresh/public/img/mtn-logo.svg",
  "mtnnigeria":  "https://www.mtn.com/wp-content/themes/mtn-refresh/public/img/mtn-logo.svg",
  "airtel":      "https://www.airtel.africa/sites/default/files/airtel-logo_0.png",
  "airtelnigeria": "https://www.airtel.africa/sites/default/files/airtel-logo_0.png",
  "airtelafrica": "https://www.airtel.africa/sites/default/files/airtel-logo_0.png",
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

function JobCard({ job, onApply, onView, isExpanded, isDark = true, user, onAuthRequired, isSaved = false, onToggleSave }) {
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
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
            <div
                style={{ fontSize: 18, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 4, letterSpacing: -0.4, lineHeight: 1.3, cursor: "pointer" }}
                onClick={(e) => { e.stopPropagation(); const slug = makeJobSlug(job.title, job.company, job.id); window.history.pushState({}, "", `/jobs/${slug}`); onView(job); }}
              >{job.title}</div>

          </div>
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
          {job.industry && <Chip variant="purple" isDark={isDark}>🏷 {job.industry}</Chip>}
        </div>

        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 14, paddingTop: 14, borderTop: isDark ? "1px solid #1e1e24" : "1px solid #e4e4ed" }}>
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
              color: "#fff",
              cursor: "pointer",
              fontFamily: "'DM Sans', sans-serif", transition: "background 0.15s",
              display: hasDirectApply(job) ? "inline-block" : "none",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "#0077ED"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = getComputedStyle(document.documentElement).getPropertyValue("--btn-primary") || "#0071E3"; }}
          >
            {!user ? "Sign in to apply" : "Apply now →"}
          </button>
        </div>
      </div>

      {/* Inline expanded detail */}
      {isExpanded && (
        <div style={{ borderTop: isDark ? "1px solid #1e1e24" : "1px solid #e4e4ed", padding: "20px 24px", background: isDark ? "#111113" : "#f8f8fb" }}>
          {/* Description */}
          <div style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 11, color: "#555", textTransform: "uppercase", letterSpacing: "0.5px", fontWeight: 500, marginBottom: 12 }}>About this role</div>
            {job.description && job.description.trim() ? (
              <div style={{ fontSize: 18, color: isDark ? "#e8e8ed" : "#1d1d1f", lineHeight: 1.9 }}>
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
                              <span style={{ color: isDark ? "#4DA3FF" : "#0071E3", flexShrink: 0, fontSize: 16, lineHeight: 1.4 }}>•</span>
                              <span style={{ flex: 1, fontSize: 18, lineHeight: 1.9 }}>{b}</span>
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
                          fontSize: isMain ? 17 : 19,
                          marginTop: isMain ? 24 : 16,
                          marginBottom: 8,
                          borderBottom: isMain ? (isDark ? "1px solid #333338" : "1px solid #e0e0e8") : "none",
                          paddingBottom: isMain ? 6 : 0,
                          textTransform: isMain ? "uppercase" : "none",
                          letterSpacing: isMain ? "0.5px" : "normal",
                          color: isMain ? (isDark ? "#ffffff" : "#1d1d1f") : (isDark ? "#4DA3FF" : "#000000"),
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
                        <p key={i} style={{ margin: "0 0 10px 0", fontSize: 18, lineHeight: 1.9, color: isDark ? "#c0c0cc" : "#1d1d1f" }}>{line}</p>
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

          {/* Action buttons — wraps on mobile */}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end", paddingTop: 16, borderTop: isDark ? "1px solid #1e1e24" : "1px solid #e4e4ed" }}>
            {/* Share */}
            <a
              href={`https://wa.me/?text=${encodeURIComponent(`${job.title} at ${job.company} — Apply on JobStream: ${window.location.origin}`)}`}
              target="_blank" rel="noreferrer"
              onClick={(e) => e.stopPropagation()}
              style={{ display: "flex", alignItems: "center", gap: 4, background: "#25D366", border: "none", borderRadius: 8, padding: "9px 12px", fontSize: 13, color: "#fff", textDecoration: "none", fontFamily: "'DM Sans', sans-serif", fontWeight: 500, whiteSpace: "nowrap" }}
            >
              📱 <span className="hide-on-xs">Share</span>
            </a>
            {/* Copy link */}
            <button
              onClick={(e) => {
                e.stopPropagation();
                navigator.clipboard.writeText(`${job.title} at ${job.company} — ${window.location.origin}`);
                toast && toast("Link copied!");
              }}
              style={{ background: isDark ? "#1e1e24" : "#f0f0f4", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 8, padding: "9px 12px", fontSize: 13, color: isDark ? "#888" : "#555", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", whiteSpace: "nowrap" }}
            >
              🔗 <span className="hide-on-xs">Copy link</span>
            </button>
            {/* Save */}
            <button
              onClick={(e) => { e.stopPropagation(); onToggleSave && onToggleSave(job); }}
              title={isSaved ? "Remove from saved" : "Save job"}
              style={{ background: isSaved ? "rgba(0,113,227,0.1)" : "none", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 8, padding: "9px 12px", fontSize: 13, color: isSaved ? "#0071E3" : (isDark ? "#888" : "#555"), cursor: "pointer", fontFamily: "'DM Sans', sans-serif", whiteSpace: "nowrap" }}
            >
              {isSaved ? "🔖" : "🔖"} <span className="hide-on-xs">{isSaved ? "Saved" : "Save"}</span>
            </button>
            {/* Close */}
            <button
              onClick={() => onView(job)}
              style={{ background: "none", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 8, padding: "9px 12px", fontSize: 13, color: "#888", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", whiteSpace: "nowrap" }}
            >
              ✕ <span className="hide-on-xs">Close</span>
            </button>
            {/* Apply on company website */}
            {job.apply_url && (
              <a href={job.apply_url} target="_blank" rel="noreferrer"
                style={{ background: isDark ? "#1e1e2e" : "#e8e8ed", border: isDark ? "1px solid rgba(0,113,227,0.35)" : "1px solid #c7c7cc", borderRadius: 8, padding: "9px 12px", fontSize: 13, color: isDark ? "#4DA3FF" : "#1d1d1f", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", textDecoration: "none", fontWeight: 500, whiteSpace: "nowrap" }}>
                🌐 <span className="hide-on-xs">Apply on company website →</span><span className="show-on-xs" style={{ display: "none" }}>Apply →</span>
              </a>
            )}
            {/* Apply now (direct) */}
            {hasDirectApply(job) && (
              <button
                onClick={() => {
                  if (!user) { onAuthRequired(); return; }
                  onApply(job);
                }}
                style={{ background: "var(--btn-primary)", border: "none", borderRadius: 8, padding: "9px 16px", fontSize: 13, fontWeight: 600, color: "#fff", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", whiteSpace: "nowrap" }}
              >
                {!user ? "Sign in to apply" : "Apply now →"}
              </button>
            )}
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
          <div style={{ width: 30, height: 30, background: "var(--btn-primary)", borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14 }}>⚡</div>
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
          <button type="submit" disabled={loading} style={{ width: "100%", padding: "12px", fontSize: 15, fontWeight: 600, background: loading ? "#ccc" : "var(--btn-primary)", color: "#fff", border: "none", borderRadius: 10, cursor: loading ? "default" : "pointer", fontFamily: "'DM Sans', sans-serif" }}>
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
          <div style={{ width: 30, height: 30, background: "var(--btn-primary)", borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14 }}>⚡</div>
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
          <button type="submit" disabled={loading} style={{ width: "100%", padding: "12px", fontSize: 15, fontWeight: 600, background: loading ? "#ccc" : "var(--btn-primary)", color: "#fff", border: "none", borderRadius: 10, cursor: loading ? "default" : "pointer", fontFamily: "'DM Sans', sans-serif" }}>
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
          <button onClick={submit} disabled={loading} style={{ background: "var(--btn-primary)", border: "none", borderRadius: 8, padding: "8px 20px", fontSize: 13, fontWeight: 500, color: "#fff", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", opacity: loading ? 0.6 : 1 }}>
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
  const [industry, setIndustryFilter] = useState("");
  const [country, setCountry] = useState("");
  const [scraping, setScraping] = useState(false);
  const [backfilling, setBackfilling] = useState(false);
  const debounceRef = useRef(null);
  const [savedIds, setSavedIds] = useState(new Set());

  // Load saved job IDs when user is logged in
  useEffect(() => {
    if (!user) return;
    api("/jobs/saved/ids").then(ids => setSavedIds(new Set(ids))).catch(() => {});
  }, [user]);

  const load = useCallback(async (q = search, t = jobType, d = dept, ind = industry, ctr = country) => {
    setLoading(true); setError("");
    try {
      const params = new URLSearchParams({ search: q, job_type: t, department: d, industry: ind, limit: 100 });
      if (ctr) params.set("location", ctr);
      const data = await api(`/jobs?${params}`);
      setJobs(data.jobs); setTotal(data.total);
    } catch (e) {
      setError("Cannot reach API at " + API + ". Is the backend running?");
    } finally { setLoading(false); }
  }, [search, jobType, dept, industry, country]);

  useEffect(() => { load("", "", "", "", ""); }, []);
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

  async function toggleSave(job) {
    if (!user) { onAuthRequired(); return; }
    const isSaved = savedIds.has(job.id);
    try {
      await api(`/jobs/${job.id}/save`, { method: isSaved ? "DELETE" : "POST" });
      setSavedIds(prev => {
        const next = new Set(prev);
        isSaved ? next.delete(job.id) : next.add(job.id);
        return next;
      });
      toast(isSaved ? "Job removed from saved" : "Job saved!");
    } catch (e) {
      toast("Failed to save job");
    }
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
          <div style={{ fontSize: 22, fontWeight: 600, color: "#f0f0f2", letterSpacing: -0.5 }}>Jobs</div>
          <div style={{ fontSize: 13, color: "#555", marginTop: 3 }}>{total} live jobs</div>
        </div>
        {user && ["super_admin","platform_admin"].includes(user.role) && (
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
        )}
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
          { val: jobType, set: (v) => { setJobType(v); load(search, v, dept, industry, country); }, opts: [
            "", "Contract", "Full-time", "Internship", "Part-time",
          ], label: "Type" },
          { val: country, set: (v) => { setCountry(v); load(search, jobType, dept, industry, v); }, opts: [
            "", "Cameroon", "Egypt", "Ethiopia", "Ghana", "Ivory Coast",
            "Kenya", "Nigeria", "Remote", "Rwanda", "Senegal",
            "South Africa", "Tanzania", "Uganda", "United Kingdom",
            "United States", "Zambia", "Zimbabwe",
          ], label: "Country" },
          { val: dept, set: (v) => { setDept(v); load(search, jobType, v, industry, country); }, opts: [
            "", "Administration", "Customer Service", "Engineering",
            "Finance", "Healthcare", "Human Resources", "Legal",
            "Marketing", "Operations", "Product", "Sales",
          ], label: "Department" },
          { val: industry, set: (v) => { setIndustryFilter(v); load(search, jobType, dept, v, country); }, opts: [
            "", "Agriculture", "Banking & Finance", "Consulting",
            "Education", "Energy & Utilities", "FMCG",
            "Government & NGO", "Healthcare", "Hospitality & Tourism",
            "Information Technology", "Insurance", "Legal",
            "Logistics & Supply Chain", "Manufacturing",
            "Media & Entertainment", "Oil & Gas",
            "Real Estate & Construction", "Retail & E-commerce",
            "Telecommunications",
          ], label: "Industry" },
        ].map(({ val, set, opts, label }) => (
          <select key={label} value={val} onChange={(e) => set(e.target.value)}
            style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 9, padding: "9px 12px", fontSize: 13, color: val ? (isDark ? "#f0f0f2" : "#1a1a1a") : (isDark ? "#666" : "#999"), fontFamily: "'DM Sans', sans-serif", outline: "none", cursor: "pointer", colorScheme: isDark ? "dark" : "light" }}>
            {opts.map((o, i) => (
              <option key={o} value={o}>
                {o || (label === "Country" ? "Country" : label === "Industry" ? "Industry" : label === "Department" ? "Department" : "Type")}
              </option>
            ))}
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
          {jobs.map((j) => <JobCard key={j.id} job={j} onApply={onApply} onView={(job) => setExpandedId(expandedId === job.id ? null : job.id)} isExpanded={expandedId === j.id} isDark={isDark} user={user} onAuthRequired={onAuthRequired} isSaved={savedIds.has(j.id)} onToggleSave={toggleSave} />)}
        </div>
      )}
    </div>
  );
}

// ── Post Job Modal ────────────────────────────────────────────────────────────
function PostJobModal({ isDark = true, onClose, onSuccess, organizations = [] }) {
  const [form, setForm] = useState({
    title: "", company: "", organization_id: "",
    location: "Lagos, Nigeria", job_type: "Full-time",
    department: "General", description: "",
    salary: "", apply_url: "", apply_email: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const set = k => e => setForm(f => ({ ...f, [k]: e.target.value }));

  const inp = { width: "100%", boxSizing: "border-box", padding: "10px 14px", fontSize: 13, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 10, background: isDark ? "#141416" : "#ffffff", color: isDark ? "#f0f0f2" : "#1d1d1f", fontFamily: "'DM Sans', sans-serif", outline: "none" };
  const sel = { ...inp, cursor: "pointer" };

  async function handleSubmit(e) {
    e.preventDefault();
    if (!form.title || !form.company) { setError("Title and company are required"); return; }
    if (!form.apply_url && !form.apply_email) { setError("Provide an apply URL or email"); return; }
    setLoading(true); setError("");
    try {
      await api("/jobs", { method: "POST", body: JSON.stringify(form) });
      onSuccess("Job posted successfully!");
      onClose();
    } catch (e) {
      setError("Failed to post job");
    } finally {
      setLoading(false);
    }
  }

  const Label = ({ children }) => (
    <label style={{ fontSize: 11, fontWeight: 600, color: isDark ? "#888" : "#555", textTransform: "uppercase", letterSpacing: "0.5px", display: "block", marginBottom: 6 }}>{children}</label>
  );

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 9000, padding: 20 }}>
      <div onClick={e => e.stopPropagation()} style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 20, width: "100%", maxWidth: 560, maxHeight: "90vh", overflowY: "auto" }}>
        <div style={{ padding: "24px 28px 16px", borderBottom: isDark ? "1px solid #2a2a32" : "1px solid #e8e8f0", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", margin: 0 }}>Post a job</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", fontSize: 20, cursor: "pointer", color: isDark ? "#666" : "#888" }}>✕</button>
        </div>
        <form onSubmit={handleSubmit} style={{ padding: "20px 28px" }}>
          {error && <div style={{ background: "rgba(245,101,101,0.1)", border: "1px solid rgba(245,101,101,0.3)", borderRadius: 8, padding: "10px 14px", marginBottom: 16, fontSize: 13, color: "#f87171" }}>{error}</div>}

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
            <div>
              <Label>Job title *</Label>
              <input value={form.title} onChange={set("title")} placeholder="Software Engineer" required style={inp} />
            </div>
            <div>
              <Label>Company *</Label>
              {organizations.length > 0 ? (
                <select value={form.organization_id} onChange={e => {
                  const org = organizations.find(o => o.id === e.target.value);
                  setForm(f => ({ ...f, organization_id: e.target.value, company: org?.name || f.company }));
                }} style={sel}>
                  <option value="">Select company…</option>
                  {organizations.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
                </select>
              ) : (
                <input value={form.company} onChange={set("company")} placeholder="Company name" required style={inp} />
              )}
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
            <div>
              <Label>Location</Label>
              <input value={form.location} onChange={set("location")} placeholder="Lagos, Nigeria" style={inp} />
            </div>
            <div>
              <Label>Job type</Label>
              <select value={form.job_type} onChange={set("job_type")} style={sel}>
                {["Full-time","Part-time","Contract","Remote","Internship"].map(t => <option key={t}>{t}</option>)}
              </select>
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
            <div>
              <Label>Department</Label>
              <input value={form.department} onChange={set("department")} placeholder="Engineering" style={inp} />
            </div>
            <div>
              <Label>Salary (optional)</Label>
              <input value={form.salary} onChange={set("salary")} placeholder="e.g. ₦300,000/month" style={inp} />
            </div>
          </div>

          <div style={{ marginBottom: 16 }}>
            <Label>Job description</Label>
            <textarea value={form.description} onChange={set("description")} placeholder="Describe the role, responsibilities, and requirements…" style={{ ...inp, height: 120, resize: "vertical" }} />
          </div>

          <div style={{ background: isDark ? "#1a1a1e" : "#f8f8fb", borderRadius: 10, padding: "14px 16px", marginBottom: 20 }}>
            <Label>How should candidates apply?</Label>
            <div style={{ marginBottom: 10 }}>
              <label style={{ fontSize: 12, color: isDark ? "#888" : "#666", display: "block", marginBottom: 4 }}>Apply URL (external link)</label>
              <input value={form.apply_url} onChange={set("apply_url")} placeholder="https://company.com/careers/apply" style={inp} />
            </div>
            <div style={{ fontSize: 11, color: isDark ? "#555" : "#aaa", textAlign: "center", margin: "8px 0" }}>— or —</div>
            <div>
              <label style={{ fontSize: 12, color: isDark ? "#888" : "#666", display: "block", marginBottom: 4 }}>Apply by email</label>
              <input value={form.apply_email} onChange={set("apply_email")} placeholder="hr@company.com" type="email" style={inp} />
            </div>
          </div>

          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
            <button type="button" onClick={onClose} style={{ background: "none", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 10, padding: "10px 20px", fontSize: 13, color: isDark ? "#888" : "#555", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>Cancel</button>
            <button type="submit" disabled={loading} style={{ background: "var(--btn-primary)", border: "none", borderRadius: 10, padding: "10px 24px", fontSize: 13, fontWeight: 600, color: "#fff", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", opacity: loading ? 0.6 : 1 }}>
              {loading ? "Posting…" : "Post job"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}


// ── Employer Dashboard Page ───────────────────────────────────────────────────
// ── Tenant Onboard Modal ─────────────────────────────────────────────────────
function TenantOnboardModal({ isDark = true, onClose, onSuccess }) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugAvailable, setSlugAvailable] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const inp = { width: "100%", boxSizing: "border-box", padding: "10px 14px", fontSize: 13, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 10, background: isDark ? "#141416" : "#ffffff", color: isDark ? "#f0f0f2" : "#1d1d1f", fontFamily: "'DM Sans', sans-serif", outline: "none" };

  useEffect(() => {
    if (!slug || slug.length < 3) { setSlugAvailable(null); return; }
    const timer = setTimeout(async () => {
      try {
        const res = await api(`/tenants/check-slug/${slug}`);
        setSlugAvailable(res.available);
      } catch { setSlugAvailable(null); }
    }, 500);
    return () => clearTimeout(timer);
  }, [slug]);

  function handleNameChange(e) {
    const n = e.target.value;
    setName(n);
    setSlug(n.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, ""));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!slugAvailable) { setError("Choose an available workspace URL"); return; }
    setLoading(true); setError("");
    try {
      const res = await api("/tenants/onboard", { method: "POST", body: JSON.stringify({ name, slug }) });
      onSuccess(res.tenant);
    } catch (e) {
      setError(e.message || "Failed to create workspace");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 9000, padding: 20 }}>
      <div onClick={e => e.stopPropagation()} style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 20, width: "100%", maxWidth: 480, padding: "32px 28px" }}>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 6 }}>Create your workspace</h2>
        <p style={{ fontSize: 13, color: isDark ? "#666" : "#888", marginBottom: 24 }}>Set up your employer workspace to post jobs and manage applications.</p>

        {error && <div style={{ background: "rgba(245,101,101,0.1)", border: "1px solid rgba(245,101,101,0.3)", borderRadius: 8, padding: "10px 14px", marginBottom: 16, fontSize: 13, color: "#f87171" }}>{error}</div>}

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 16 }}>
            <label style={{ fontSize: 11, fontWeight: 600, color: isDark ? "#888" : "#555", textTransform: "uppercase", letterSpacing: "0.5px", display: "block", marginBottom: 6 }}>Company name</label>
            <input value={name} onChange={handleNameChange} placeholder="Acme Corp" required style={inp} />
          </div>

          <div style={{ marginBottom: 24 }}>
            <label style={{ fontSize: 11, fontWeight: 600, color: isDark ? "#888" : "#555", textTransform: "uppercase", letterSpacing: "0.5px", display: "block", marginBottom: 6 }}>Workspace URL</label>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 12, color: isDark ? "#555" : "#aaa", whiteSpace: "nowrap" }}>jobstream.ng/</span>
              <input value={slug} onChange={e => setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))} placeholder="acme-corp" required style={{ ...inp, flex: 1 }} />
              {slug.length >= 3 && (
                <span style={{ fontSize: 18, flexShrink: 0 }}>
                  {slugAvailable === true ? "✅" : slugAvailable === false ? "❌" : "⏳"}
                </span>
              )}
            </div>
            {slugAvailable === false && <div style={{ fontSize: 11, color: "#f87171", marginTop: 4 }}>This URL is taken. Try another.</div>}
            {slugAvailable === true && <div style={{ fontSize: 11, color: "#3DD68C", marginTop: 4 }}>Available!</div>}
          </div>

          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
            <button type="button" onClick={onClose} style={{ background: "none", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 10, padding: "10px 20px", fontSize: 13, color: isDark ? "#888" : "#555", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>Cancel</button>
            <button type="submit" disabled={loading || !slugAvailable} style={{ background: slugAvailable ? "#0071E3" : "#888", border: "none", borderRadius: 10, padding: "10px 24px", fontSize: 13, fontWeight: 600, color: "#fff", cursor: slugAvailable ? "pointer" : "default", fontFamily: "'DM Sans', sans-serif" }}>
              {loading ? "Creating…" : "Create workspace"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}


function EmployerPage({ isDark = true, user, onAuthRequired, toast, can = () => true }) {
  const [jobs, setJobs] = useState([]);
  const [organizations, setOrganizations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showPostJob, setShowPostJob] = useState(false);
  const [showOnboard, setShowOnboard] = useState(false);
  const [tenant, setTenant] = useState(null);
  const [selectedJob, setSelectedJob] = useState(null);
  const [applications, setApplications] = useState([]);
  const [appsLoading, setAppsLoading] = useState(false);

  useEffect(() => {
    if (!user) return;
    Promise.all([
      api("/jobs?source=manual&limit=100"),
      api("/organizations"),
      api("/workspace/overview").catch(() => null),
    ]).then(([jobsData, orgs, _workspace]) => {
      setJobs((jobsData.jobs || []).filter(j => j.source === "manual"));
      setOrganizations(orgs);
      // tenant is populated separately via onboarding, not needed here
    }).catch(() => {})
    .finally(() => setLoading(false));
  }, [user]);

  async function loadApplications(job) {
    setSelectedJob(job);
    setAppsLoading(true);
    try {
      const apps = await api(`/jobs/${job.id}/applications`);
      setApplications(apps);
    } catch (e) {
      toast("Failed to load applications");
    } finally {
      setAppsLoading(false);
    }
  }

  async function updateStatus(appId, status) {
    try {
      await api(`/applications/${appId}/status`, { method: "PATCH", body: JSON.stringify({ status }) });
      setApplications(prev => prev.map(a => a.id === appId ? { ...a, status } : a));
      toast(`Status updated to ${status}`);
    } catch { toast("Failed to update status"); }
  }

  async function deleteJob(job) {
    try {
      await api(`/jobs/${job.id}`, { method: "DELETE" });
      setJobs(prev => prev.filter(j => j.id !== job.id));
      if (selectedJob?.id === job.id) setSelectedJob(null);
      toast("Job removed");
    } catch { toast("Failed to remove job"); }
  }

  const statusColors = {
    new:         "#0071E3",
    reviewing:   "#F5A623",
    shortlisted: "#3DD68C",
    interview:   "#9B59B6",
    offer:       "#2ECC71",
    hired:       "#27AE60",
    rejected:    "#f87171",
    withdrawn:   "#888",
  };

  if (!user) return (
    <div style={{ textAlign: "center", padding: 60 }}>
      <div style={{ fontSize: 40, marginBottom: 16 }}>🏢</div>
      <div style={{ fontSize: 18, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 8 }}>Employer Dashboard</div>
      <div style={{ fontSize: 14, color: isDark ? "#666" : "#888", marginBottom: 24 }}>Sign in to post jobs and manage applications</div>
      <button onClick={onAuthRequired} style={{ background: "var(--btn-primary)", color: "#fff", border: "none", borderRadius: 10, padding: "10px 24px", fontSize: 14, fontWeight: 600, cursor: "pointer" }}>Sign in | Register</button>
    </div>
  );

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24, flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", letterSpacing: -0.5, marginBottom: 4 }}>Employer Dashboard</h1>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <p style={{ fontSize: 13, color: isDark ? "#666" : "#888", margin: 0 }}>{jobs.length} active job{jobs.length !== 1 ? "s" : ""} posted</p>
            {tenant ? (
              <span style={{ fontSize: 11, background: "rgba(0,113,227,0.1)", color: "#0071E3", padding: "2px 10px", borderRadius: 20, fontWeight: 500 }}>
                {tenant.name} · {tenant.plan}
              </span>
            ) : (
              <button onClick={() => setShowOnboard(true)} style={{ fontSize: 11, background: "rgba(61,214,140,0.1)", color: "#3DD68C", border: "1px solid rgba(61,214,140,0.3)", padding: "2px 10px", borderRadius: 20, cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>
                + Create workspace
              </button>
            )}
          </div>
        </div>
        {(can("job.create") || !user?.tenant_id) && (
          <button onClick={() => setShowPostJob(true)} style={{ background: "var(--btn-primary)", border: "none", borderRadius: 10, padding: "10px 20px", fontSize: 13, fontWeight: 600, color: "#fff", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>
            + Post a job
          </button>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: selectedJob ? "1fr 1fr" : "1fr", gap: 16 }}>
        {/* Jobs list */}
        <div>
          <h2 style={{ fontSize: 14, fontWeight: 600, color: isDark ? "#888" : "#666", marginBottom: 12, textTransform: "uppercase", letterSpacing: "0.5px" }}>Your jobs</h2>
          {loading && <Spinner />}
          {!loading && jobs.length === 0 && (
            <div style={{ textAlign: "center", padding: "32px 20px", background: isDark ? "#141416" : "#f8f8fb", borderRadius: 14, border: isDark ? "1px solid #2a2a32" : "1px solid #e8e8f0" }}>
              <div style={{ fontSize: 14, color: isDark ? "#666" : "#888", marginBottom: 12 }}>No jobs posted yet</div>
              <button onClick={() => setShowPostJob(true)} style={{ background: "var(--btn-primary)", color: "#fff", border: "none", borderRadius: 8, padding: "8px 18px", fontSize: 13, cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>Post your first job</button>
            </div>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {jobs.map(job => (
              <div
                key={job.id}
                onClick={() => loadApplications(job)}
                style={{ background: isDark ? "#141416" : "#ffffff", border: `1px solid ${selectedJob?.id === job.id ? "#0071E3" : (isDark ? "#2a2a32" : "#e0e0e8")}`, borderRadius: 12, padding: "14px 16px", cursor: "pointer", transition: "border-color 0.15s" }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 2 }}>{job.title}</div>
                    <div style={{ fontSize: 12, color: isDark ? "#666" : "#888" }}>{job.company} · {job.location}</div>
                  </div>
                  <button
                    onClick={e => { e.stopPropagation(); deleteJob(job); }}
                    style={{ background: "none", border: "none", cursor: "pointer", color: "#f87171", fontSize: 16, padding: 2 }}
                    title="Remove job"
                  >✕</button>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Applications panel */}
        {selectedJob && (
          <div>
            <h2 style={{ fontSize: 14, fontWeight: 600, color: isDark ? "#888" : "#666", marginBottom: 12, textTransform: "uppercase", letterSpacing: "0.5px" }}>
              Applications — {selectedJob.title}
            </h2>
            {appsLoading && <Spinner />}
            {!appsLoading && applications.length === 0 && (
              <div style={{ textAlign: "center", padding: "32px 20px", background: isDark ? "#141416" : "#f8f8fb", borderRadius: 14, border: isDark ? "1px solid #2a2a32" : "1px solid #e8e8f0" }}>
                <div style={{ fontSize: 13, color: isDark ? "#666" : "#888" }}>No applications yet</div>
              </div>
            )}
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {applications.map(app => (
                <div key={app.id} style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 12, padding: "14px 16px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
                    <div>
                      <div style={{ fontSize: 14, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f" }}>{app.name}</div>
                      <div style={{ fontSize: 12, color: isDark ? "#666" : "#888" }}>{app.email}</div>
                    </div>
                    <span style={{ fontSize: 11, fontWeight: 600, color: statusColors[app.status] || "#888", background: "rgba(0,0,0,0.05)", padding: "3px 10px", borderRadius: 20, textTransform: "capitalize" }}>
                      {app.status || "new"}
                    </span>
                  </div>
                  {app.cover_note && (
                    <p style={{ fontSize: 12, color: isDark ? "#888" : "#666", margin: "0 0 10px", lineHeight: 1.5 }}>{app.cover_note}</p>
                  )}
                  {app.resume_url && (
                    <a href={app.resume_url} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: "#0071E3", textDecoration: "none", display: "block", marginBottom: 10 }}>📎 View CV</a>
                  )}
                  {/* Status update */}
                  <select
                    value={app.status || "new"}
                    onChange={e => updateStatus(app.id, e.target.value)}
                    style={{ fontSize: 11, padding: "4px 8px", borderRadius: 6, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", background: isDark ? "#1e1e24" : "#f8f8fb", color: isDark ? "#888" : "#555", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}
                  >
                    {["new","reviewing","shortlisted","interview","offer","hired","rejected","withdrawn"].map(s => (
                      <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {showOnboard && (
        <TenantOnboardModal
          isDark={isDark}
          onClose={() => setShowOnboard(false)}
          onSuccess={(t) => { setTenant(t); setShowOnboard(false); toast("Workspace created!"); }}
        />
      )}

      {showPostJob && (
        <PostJobModal
          isDark={isDark}
          organizations={organizations}
          onClose={() => setShowPostJob(false)}
          onSuccess={msg => { toast(msg); setShowPostJob(false); api("/jobs?source=manual&limit=100").then(d => setJobs((d.jobs||[]).filter(j=>j.source==="manual"))); }}
        />
      )}
    </div>
  );
}



// ── Platform Admin Dashboard ──────────────────────────────────────────────────
// ── Email Template Editor ────────────────────────────────────────────────────
function EmailTemplateEditor({ isDark, template, setTemplate, templateDirty,
  setTemplateDirty, saveTemplate, resetTemplate, toast, user }) {

  const [editorTab, setEditorTab] = useState("gui");
  const [sending, setSending] = useState(false);
  const [testEmail, setTestEmail] = useState(user?.email || "");

  // GUI design state — maps to template placeholders
  const [guiSettings, setGuiSettings] = useState(() => ({
    headerTitle: "⚡ JobStream",
    headerSubtitle: "New jobs for you",
    accentColor: "#0071E3",
    bgColor: "#f4f4f6",
    cardBg: "#ffffff",
    fontFamily: "Arial, sans-serif",
    showLocation: true,
    showIndustry: true,
    buttonText: "View all jobs",
    footerText: "You are receiving this because you set up a job alert.",
    maxJobs: 5,
  }));

  // Sample data for preview
  const SAMPLE_JOBS = [
    { title: "Senior Network Engineer", company: "MTN Nigeria", location: "Lagos, Nigeria", industry: "Telecommunications" },
    { title: "Software Developer", company: "Airtel Africa", location: "Abuja, Nigeria", industry: "Telecommunications" },
    { title: "Product Manager", company: "Interswitch", location: "Lagos, Nigeria", industry: "Banking & Finance" },
  ];

  function buildPreviewHtml(settings, sampleJobs) {
    const jobsHtml = sampleJobs.slice(0, settings.maxJobs).map(j => `
      <div style="padding:12px 0;border-bottom:1px solid #f0f0f4">
        <a href="#" style="font-size:14px;font-weight:600;color:${settings.accentColor};text-decoration:none">${j.title}</a>
        <div style="font-size:12px;color:#888;margin-top:3px">
          ${j.company}${settings.showLocation ? ` · ${j.location}` : ""}${settings.showIndustry && j.industry ? ` · ${j.industry}` : ""}
        </div>
      </div>`).join("");

    return `<!DOCTYPE html>
<html>
<body style="font-family:${settings.fontFamily};background:${settings.bgColor};margin:0;padding:20px;">
<div style="max-width:480px;margin:0 auto;background:${settings.cardBg};border-radius:16px;padding:36px;">
  <h1 style="font-size:18px;color:#1d1d1f;margin:0 0 4px">${settings.headerTitle}</h1>
  <h2 style="font-size:20px;color:#1d1d1f;margin:0 0 6px">${settings.headerSubtitle}</h2>
  <p style="font-size:13px;color:#888;margin:0 0 20px">
    Matching: <strong>Network Engineer, Software Developer</strong> · Lagos, Nigeria · Telecommunications
  </p>
  ${jobsHtml}
  <div style="text-align:center;margin-top:24px">
    <a href="#" style="display:inline-block;padding:12px 28px;background:${settings.accentColor};
       color:#fff;border-radius:10px;text-decoration:none;font-weight:600;font-size:14px">
      ${settings.buttonText}
    </a>
  </div>
  <p style="font-size:11px;color:#ccc;text-align:center;margin-top:24px">${settings.footerText}</p>
  <p style="font-size:10px;color:#ddd;text-align:center;margin:4px 0 0">
    <a href="#" style="color:#ccc">Unsubscribe</a>
  </p>
</div>
</body>
</html>`;
  }

  function guiToTemplate(settings) {
    return `<!DOCTYPE html>
<html>
<body style="font-family:${settings.fontFamily};background:${settings.bgColor};margin:0;padding:20px;">
<div style="max-width:480px;margin:0 auto;background:${settings.cardBg};border-radius:16px;padding:36px;">
  <h1 style="font-size:18px;color:#1d1d1f;margin:0 0 4px">${settings.headerTitle}</h1>
  <h2 style="font-size:20px;color:#1d1d1f;margin:0 0 6px">${settings.headerSubtitle}</h2>
  <p style="font-size:13px;color:#888;margin:0 0 20px">
    Matching: <strong>{{keywords}}</strong>{{#if location}} · {{location}}{{/if}}{{#if industry}} · {{industry}}{{/if}}
  </p>
  {{jobs_html}}
  <div style="text-align:center;margin-top:24px">
    <a href="{{app_url}}" style="display:inline-block;padding:12px 28px;background:${settings.accentColor};
       color:#fff;border-radius:10px;text-decoration:none;font-weight:600;font-size:14px">
      ${settings.buttonText}
    </a>
  </div>
  <p style="font-size:11px;color:#ccc;text-align:center;margin-top:24px">${settings.footerText}</p>
  <p style="font-size:10px;color:#ddd;text-align:center;margin:4px 0 0">
    <a href="{{unsubscribe_url}}" style="color:#ccc">Unsubscribe</a>
  </p>
</div>
</body>
</html>`;
  }

  function updateGui(key, val) {
    const next = { ...guiSettings, [key]: val };
    setGuiSettings(next);
    const tmpl = guiToTemplate(next);
    setTemplate(tmpl);
    setTemplateDirty(true);
  }

  async function sendTestEmail() {
    if (!testEmail.trim()) { toast("Enter an email address"); return; }
    setSending(true);
    try {
      await api("/admin/alert-template/test", {
        method: "POST",
        body: JSON.stringify({ email: testEmail, template }),
      });
      toast(`Test email sent to ${testEmail}`);
    } catch (e) { toast(e.message || "Send failed"); }
    finally { setSending(false); }
  }

  const inp = { boxSizing: "border-box", padding: "7px 10px", fontSize: 12, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 7, background: isDark ? "#141416" : "#fff", color: isDark ? "#f0f0f2" : "#1d1d1f", fontFamily: "'DM Sans', sans-serif", outline: "none" };
  const lbl = { fontSize: 10, fontWeight: 600, color: isDark ? "#666" : "#888", textTransform: "uppercase", letterSpacing: "0.4px", display: "block", marginBottom: 4 };
  const tabBtnStyle = (t) => ({
    background: editorTab === t ? "#0071E3" : "none",
    border: editorTab === t ? "none" : isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8",
    borderRadius: 7, padding: "5px 14px", fontSize: 12,
    color: editorTab === t ? "#fff" : isDark ? "#888" : "#555",
    cursor: "pointer", fontFamily: "'DM Sans', sans-serif",
  });

  const previewHtml = buildPreviewHtml(guiSettings, SAMPLE_JOBS);

  return (
    <div style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "20px 22px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14, flexWrap: "wrap", gap: 8 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f" }}>Alert Email Template</div>
          <div style={{ fontSize: 11, color: isDark ? "#555" : "#aaa", marginTop: 2 }}>Design the email every alert subscriber receives</div>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button onClick={() => setEditorTab("gui")}    style={tabBtnStyle("gui")}>🎨 Designer</button>
          <button onClick={() => setEditorTab("preview")} style={tabBtnStyle("preview")}>👁 Preview</button>
          <button onClick={() => setEditorTab("html")}   style={tabBtnStyle("html")}>{"</>"} HTML</button>
        </div>
      </div>

      {/* Designer tab */}
      {editorTab === "gui" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div>
            <label style={lbl}>Header title</label>
            <input value={guiSettings.headerTitle} onChange={e => updateGui("headerTitle", e.target.value)} style={{ ...inp, width: "100%", marginBottom: 8 }} />
            <label style={lbl}>Header subtitle</label>
            <input value={guiSettings.headerSubtitle} onChange={e => updateGui("headerSubtitle", e.target.value)} style={{ ...inp, width: "100%", marginBottom: 8 }} />
            <label style={lbl}>Button text</label>
            <input value={guiSettings.buttonText} onChange={e => updateGui("buttonText", e.target.value)} style={{ ...inp, width: "100%", marginBottom: 8 }} />
            <label style={lbl}>Footer text</label>
            <input value={guiSettings.footerText} onChange={e => updateGui("footerText", e.target.value)} style={{ ...inp, width: "100%", marginBottom: 8 }} />
            <label style={lbl}>Max jobs shown</label>
            <select value={guiSettings.maxJobs} onChange={e => updateGui("maxJobs", Number(e.target.value))} style={{ ...inp, width: "100%", marginBottom: 8, cursor: "pointer" }}>
              {[3,5,8,10].map(n => <option key={n} value={n}>{n} jobs</option>)}
            </select>
          </div>
          <div>
            <label style={lbl}>Accent colour (button/links)</label>
            <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
              <input type="color" value={guiSettings.accentColor} onChange={e => updateGui("accentColor", e.target.value)} style={{ width: 40, height: 32, border: "none", borderRadius: 6, cursor: "pointer", background: "none", padding: 0 }} />
              <input value={guiSettings.accentColor} onChange={e => updateGui("accentColor", e.target.value)} style={{ ...inp, flex: 1 }} />
            </div>
            <label style={lbl}>Background colour</label>
            <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
              <input type="color" value={guiSettings.bgColor} onChange={e => updateGui("bgColor", e.target.value)} style={{ width: 40, height: 32, border: "none", borderRadius: 6, cursor: "pointer", background: "none", padding: 0 }} />
              <input value={guiSettings.bgColor} onChange={e => updateGui("bgColor", e.target.value)} style={{ ...inp, flex: 1 }} />
            </div>
            <label style={lbl}>Card background</label>
            <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
              <input type="color" value={guiSettings.cardBg} onChange={e => updateGui("cardBg", e.target.value)} style={{ width: 40, height: 32, border: "none", borderRadius: 6, cursor: "pointer", background: "none", padding: 0 }} />
              <input value={guiSettings.cardBg} onChange={e => updateGui("cardBg", e.target.value)} style={{ ...inp, flex: 1 }} />
            </div>
            <label style={lbl}>Font family</label>
            <select value={guiSettings.fontFamily} onChange={e => updateGui("fontFamily", e.target.value)} style={{ ...inp, width: "100%", marginBottom: 8, cursor: "pointer" }}>
              <option value="Arial, sans-serif">Arial</option>
              <option value="'Helvetica Neue', Helvetica, sans-serif">Helvetica Neue</option>
              <option value="Georgia, serif">Georgia</option>
              <option value="'Trebuchet MS', sans-serif">Trebuchet MS</option>
            </select>
            <div style={{ display: "flex", gap: 16, marginTop: 4 }}>
              <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: isDark ? "#aaa" : "#555", cursor: "pointer" }}>
                <input type="checkbox" checked={guiSettings.showLocation} onChange={e => updateGui("showLocation", e.target.checked)} />
                Show location
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: isDark ? "#aaa" : "#555", cursor: "pointer" }}>
                <input type="checkbox" checked={guiSettings.showIndustry} onChange={e => updateGui("showIndustry", e.target.checked)} />
                Show industry
              </label>
            </div>
          </div>
        </div>
      )}

      {/* Preview tab */}
      {editorTab === "preview" && (
        <div style={{ border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 10, overflow: "hidden" }}>
          <div style={{ background: isDark ? "#1a1a1e" : "#f0f0f4", padding: "8px 12px", fontSize: 11, color: isDark ? "#555" : "#888" }}>
            📧 Email preview with sample data
          </div>
          <iframe srcDoc={previewHtml} style={{ width: "100%", height: 500, border: "none", background: "#fff" }} title="Email preview" />
        </div>
      )}

      {/* HTML tab */}
      {editorTab === "html" && (
        <div>
          <div style={{ fontSize: 11, color: isDark ? "#555" : "#aaa", marginBottom: 8 }}>
            Direct HTML edit. Placeholders: <code style={{ color: "#0071E3" }}>{"{{keywords}} {{jobs_html}} {{app_url}} {{unsubscribe_url}}"}</code>
          </div>
          <textarea value={template} onChange={e => { setTemplate(e.target.value); setTemplateDirty(true); }}
            style={{ width: "100%", boxSizing: "border-box", height: 320, padding: "10px 12px", fontSize: 11, fontFamily: "'DM Mono', monospace", borderRadius: 8, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", background: isDark ? "#1a1a1e" : "#f8f8fb", color: isDark ? "#ccc" : "#333", outline: "none", resize: "vertical" }} />
        </div>
      )}

      {/* Action bar */}
      <div style={{ display: "flex", gap: 8, marginTop: 14, flexWrap: "wrap", alignItems: "center" }}>
        <input value={testEmail} onChange={e => setTestEmail(e.target.value)}
          placeholder="Test email address"
          style={{ ...inp, width: 200 }} />
        <button onClick={sendTestEmail} disabled={sending}
          style={{ background: "#9B59B6", border: "none", borderRadius: 8, padding: "7px 14px", fontSize: 12, fontWeight: 600, color: "#fff", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", opacity: sending ? 0.7 : 1 }}>
          {sending ? "Sending…" : "📧 Send test"}
        </button>
        <div style={{ flex: 1 }} />
        <button onClick={resetTemplate} style={{ background: "none", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 8, padding: "7px 14px", fontSize: 12, color: isDark ? "#666" : "#555", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>Reset</button>
        <button onClick={saveTemplate} disabled={!templateDirty}
          style={{ background: templateDirty ? "#0071E3" : (isDark ? "#222" : "#ddd"), border: "none", borderRadius: 8, padding: "7px 16px", fontSize: 12, fontWeight: 600, color: templateDirty ? "#fff" : (isDark ? "#444" : "#aaa"), cursor: templateDirty ? "pointer" : "default", fontFamily: "'DM Sans', sans-serif" }}>
          {templateDirty ? "Save template" : "✓ Saved"}
        </button>
      </div>
    </div>
  );
}


// ── Nav Settings Editor ──────────────────────────────────────────────────────
function NavSettingsEditor({ isDark, toast }) {
  const ALL_ITEMS = [
    { id: "jobs",         label: "💼 Jobs" },
    { id: "companies",    label: "🏢 Companies" },
    { id: "postjob",      label: "➕ Post a Job" },
    { id: "myapps",       label: "📨 My Applications" },
    { id: "saved",        label: "🔖 Saved Jobs" },
    { id: "employer",     label: "🏢 Employer Dashboard" },
    { id: "applications", label: "📋 Applications Pipeline" },
    { id: "ai",           label: "✨ AI Tools" },
    { id: "billing",      label: "💳 Billing" },
    { id: "analytics",    label: "📊 Analytics" },
    { id: "workspace",    label: "📊 Workspace" },
    { id: "admin",        label: "⚙️ Admin" },
    { id: "scraper",      label: "🤖 Streamer" },
  ];

  const GROUPS = [
    { key: "guest",     label: "👤 Guests (not logged in)" },
    { key: "candidate", label: "🎓 Candidates" },
    { key: "employer",  label: "🏢 Employers / HR" },
    { key: "admin",     label: "⚙️ Admins" },
  ];

  const DEFAULT = {
    guest:     ["jobs", "companies", "postjob"],
    candidate: ["jobs", "companies", "myapps", "saved", "ai", "billing"],
    employer:  ["jobs", "companies", "employer", "applications", "analytics", "billing"],
    admin:     ["jobs", "companies", "myapps", "saved", "employer", "applications",
                "ai", "billing", "analytics", "workspace", "admin", "scraper"],
  };

  const [settings, setSettings] = useState(DEFAULT);
  const [loading, setLoading] = useState(true);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    api("/admin/settings/nav").then(d => {
      setSettings({ ...DEFAULT, ...d });
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  function toggle(group, id) {
    setSettings(prev => {
      const current = prev[group] || [];
      const next = current.includes(id)
        ? current.filter(x => x !== id)
        : [...current, id];
      return { ...prev, [group]: next };
    });
    setDirty(true);
  }

  async function save() {
    try {
      await api("/admin/settings/nav", { method: "POST", body: JSON.stringify(settings) });
      setDirty(false);
      toast("Nav settings saved — users will see changes on next page load");
    } catch(e) { toast(e.message || "Failed to save"); }
  }

  async function resetToDefault() {
    setSettings(DEFAULT);
    setDirty(true);
  }

  if (loading) return <Spinner />;

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 16, marginBottom: 16 }}>
        {GROUPS.map(group => (
          <div key={group.key} style={{ background: isDark ? "#1a1a1e" : "#f8f8fb", borderRadius: 10, padding: "14px 16px" }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: isDark ? "#aaa" : "#555", marginBottom: 10 }}>{group.label}</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {ALL_ITEMS.map(item => {
                const checked = (settings[group.key] || []).includes(item.id);
                const locked = group.key === "admin" && ["admin","scraper"].includes(item.id);
                return (
                  <label key={item.id} style={{ display: "flex", alignItems: "center", gap: 8, cursor: locked ? "default" : "pointer", opacity: locked ? 0.5 : 1 }}>
                    <input type="checkbox" checked={checked} disabled={locked}
                      onChange={() => !locked && toggle(group.key, item.id)}
                      style={{ accentColor: "#0071E3", width: 14, height: 14 }} />
                    <span style={{ fontSize: 12, color: isDark ? "#ccc" : "#333" }}>{item.label}</span>
                    {locked && <span style={{ fontSize: 10, color: isDark ? "#444" : "#bbb" }}>always on</span>}
                  </label>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button onClick={resetToDefault} style={{ background: "none", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 8, padding: "7px 14px", fontSize: 12, color: isDark ? "#666" : "#555", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>Reset defaults</button>
        <button onClick={save} disabled={!dirty}
          style={{ background: dirty ? "#0071E3" : (isDark ? "#222" : "#ddd"), border: "none", borderRadius: 8, padding: "7px 16px", fontSize: 12, fontWeight: 600, color: dirty ? "#fff" : (isDark ? "#444" : "#aaa"), cursor: dirty ? "pointer" : "default", fontFamily: "'DM Sans', sans-serif" }}>
          {dirty ? "Save nav settings" : "✓ Saved"}
        </button>
      </div>
    </div>
  );
}


function AdminDashboardPage({ isDark = true, user, onAuthRequired, toast }) {
  const [overview, setOverview] = useState(null);
  const [users, setUsers] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [industries, setIndustries] = useState([]);
  const [newIndustry, setNewIndustry] = useState("");
  const [template, setTemplate] = useState("");
  const [templateDirty, setTemplateDirty] = useState(false);
  const [themeSettings, setThemeSettings] = useState({ accent_color: "#0071E3", btn_color_dark: "#0071E3", btn_color_light: "#000000", bg_dark: "#0a0a0c", bg_light: "#f5f5f7" });
  const [themeDirty, setThemeDirty] = useState(false);
  const [streamerHours, setStreamerHours] = useState(4);
  const [streamerDirty, setStreamerDirty] = useState(false);
  const [backfilling, setBackfillingInd] = useState(false);
  const [brandSettings, setBrandSettings] = useState({ name: "JobStream", logo_url: "" });
  const [brandDirty, setBrandDirty] = useState(false);
  const [editingJob, setEditingJob] = useState(null);
  const [jobSearch, setJobSearch] = useState("");
  const [jobStatusFilter, setJobStatusFilter] = useState("");
  const [jobPage, setJobPage] = useState(0);
  const JOB_PAGE_SIZE = 20;
  const [tab, setTab] = useState("overview");
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  const [userSearch, setUserSearch] = useState("");
  const [userRoleFilter, setUserRoleFilter] = useState("");
  const [addingUser, setAddingUser] = useState(false);
  const [newUser, setNewUser] = useState({ full_name: "", email: "", password: "", role: "candidate", send_confirmation: true });
  const [assigningRole, setAssigningRole] = useState(null); // user being role-assigned

  const ALL_ROLES = [
    "candidate", "premium_candidate",
    "org_owner", "hr_admin", "recruiter", "hiring_manager", "interviewer",
    "super_admin", "platform_admin", "support_agent",
  ];

  const JOB_TYPES = ["Full-time", "Part-time", "Contract", "Internship"];
  const DEPARTMENTS = [
    "General", "Engineering & IT", "Sales & Business Development",
    "Marketing & Communications", "Finance & Accounting", "Human Resources",
    "Operations & Logistics", "Customer Service", "Legal & Compliance",
    "Product & Design", "Administration", "Healthcare",
    "Engineering (Field/Technical Trades)",
  ];

  const isAdmin = user && ["super_admin", "platform_admin"].includes(user.role);

  useEffect(() => {
    if (!isAdmin) return;
    api("/admin/overview").then(setOverview).catch(() => {}).finally(() => setLoading(false));
  }, [isAdmin]);

  async function loadTab(t) {
    setTab(t); setLoading(true);
    try {
      if (t === "users")      setUsers((await api("/admin/users?limit=100")).users || []);
      if (t === "jobs") {
        setJobPage(0);
        const q = jobSearch ? `&search=${encodeURIComponent(jobSearch)}` : "";
        const s = jobStatusFilter ? `&is_active=${jobStatusFilter}` : "";
        setJobs((await api(`/admin/jobs?limit=200${q}${s}`)).jobs || []);
      }
      if (t === "tenants")    setTenants((await api("/admin/tenants?limit=100")).tenants || []);
      if (t === "alerts")     setAlerts((await api("/admin/alerts?limit=100")).alerts || []);
      if (t === "settings") {
        const [m, tmpl, theme, streamer, brand] = await Promise.all([
          api("/admin/industries"),
          api("/admin/alert-template"),
          api("/admin/settings/theme"),
          api("/admin/settings/streamer"),
          api("/admin/settings/brand").catch(() => ({ name: "JobStream", logo_url: "" })),
        ]);
        setIndustries(m.industries || []);
        setTemplate(tmpl.template || "");
        setTemplateDirty(false);
        setThemeSettings(theme || { accent_color: "#0071E3", btn_color_dark: "#0071E3", btn_color_light: "#000000", bg_dark: "#0a0a0c", bg_light: "#f5f5f7" });
        setThemeDirty(false);
        setStreamerHours(streamer?.scrape_interval_hours || 4);
        setStreamerDirty(false);
        setBrandSettings(brand || { name: "JobStream", logo_url: "" });
        setBrandDirty(false);
      }
    } catch (e) { toast("Failed to load data"); }
    finally { setLoading(false); }
  }

  async function adminJobAction(action, job) {
    try {
      if (action === "publish")   await api(`/admin/jobs/${job.id}/publish`,   { method: "POST" });
      if (action === "unpublish") await api(`/admin/jobs/${job.id}/unpublish`, { method: "POST" });
      if (action === "delete")    await api(`/admin/jobs/${job.id}/hard`,      { method: "DELETE" });
      if (action === "publish" || action === "unpublish") {
        setJobs(prev => prev.map(j => j.id === job.id
          ? { ...j, is_active: action === "publish" ? 1 : 0 } : j));
      }
      if (action === "delete") setJobs(prev => prev.filter(j => j.id !== job.id));
      toast(action === "delete" ? "Job permanently deleted" : `Job ${action}ed`);
    } catch (e) { toast(`Failed: ${e.message}`); }
  }

  async function saveJobEdit(updates) {
    try {
      await api(`/admin/jobs/${editingJob.id}`, { method: "PATCH", body: JSON.stringify(updates) });
      setJobs(prev => prev.map(j => j.id === editingJob.id ? { ...j, ...updates } : j));
      setEditingJob(null);
      toast("Job saved");
    } catch (e) { toast(`Failed: ${e.message}`); }
  }

  async function addIndustry() {
    if (!newIndustry.trim()) return;
    try {
      const res = await api(`/admin/industries?name=${encodeURIComponent(newIndustry.trim())}`, { method: "POST" });
      setIndustries(res.industries || []);
      setNewIndustry("");
      toast(`Added "${newIndustry.trim()}"`);
    } catch (e) { toast(`Failed: ${e.message}`); }
  }

  async function removeIndustry(name) {
    try {
      const res = await api(`/admin/industries/${encodeURIComponent(name)}`, { method: "DELETE" });
      setIndustries(res.industries || []);
      toast(`Removed "${name}"`);
    } catch (e) { toast(e.message || "Failed"); }
  }

  async function saveTemplate() {
    try {
      await api("/admin/alert-template", { method: "POST", body: JSON.stringify({ template }) });
      setTemplateDirty(false);
      toast("Template saved");
    } catch (e) { toast(`Failed: ${e.message}`); }
  }

  async function resetTemplate() {
    try {
      const res = await api("/admin/alert-template/reset", { method: "POST" });
      setTemplate(res.template || "");
      setTemplateDirty(false);
      toast("Template reset to default");
    } catch (e) { toast(`Failed: ${e.message}`); }
  }

  if (!user) return (
    <div style={{ textAlign: "center", padding: 60 }}>
      <div style={{ fontSize: 40, marginBottom: 16 }}>🔐</div>
      <div style={{ fontSize: 14, color: isDark ? "#666" : "#888", marginBottom: 24 }}>Admin access required</div>
      <button onClick={onAuthRequired} style={{ background: "var(--btn-primary)", color: "#fff", border: "none", borderRadius: 10, padding: "10px 24px", fontSize: 14, fontWeight: 600, cursor: "pointer" }}>Sign in</button>
    </div>
  );

  if (!isAdmin) return (
    <div style={{ textAlign: "center", padding: 60 }}>
      <div style={{ fontSize: 40, marginBottom: 16 }}>🚫</div>
      <div style={{ fontSize: 16, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 8 }}>Access Denied</div>
      <div style={{ fontSize: 13, color: isDark ? "#666" : "#888" }}>Platform admin access required</div>
    </div>
  );

  const tabs = [
    { id: "overview",  label: "📊 Overview"  },
    { id: "jobs",      label: "💼 Jobs"      },
    { id: "tenants",   label: "🏢 Tenants"   },
    { id: "users",     label: "👥 Users"     },
    { id: "alerts",    label: "🔔 Alerts"    },
    { id: "settings",  label: "⚙️ Settings"  },
  ];

  const tabStyle = (t) => ({
    background: tab === t ? "#0071E3" : "none",
    border: tab === t ? "none" : isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8",
    borderRadius: 8, padding: "7px 16px", fontSize: 13,
    color: tab === t ? "#fff" : isDark ? "#888" : "#555",
    cursor: "pointer", fontFamily: "'DM Sans', sans-serif", fontWeight: tab === t ? 600 : 400,
  });

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", letterSpacing: -0.5, marginBottom: 4 }}>Platform Admin</h1>
        <p style={{ fontSize: 13, color: isDark ? "#666" : "#888" }}>Manage tenants, users, jobs and platform health</p>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 8, marginBottom: 24, flexWrap: "wrap" }}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => loadTab(t.id)} style={tabStyle(t.id)}>{t.label}</button>
        ))}
      </div>

      {loading && <Spinner />}

      {/* Overview */}
      {tab === "overview" && overview && !loading && (
        <div>
          <div style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap" }}>
            <StatCard label="Total users"     value={overview.users?.total}     sub={`+${overview.users?.new_30d} last 30d`}      isDark={isDark} />
            <StatCard label="Active tenants"  value={overview.tenants?.active}  sub={`${overview.tenants?.total} total`}           isDark={isDark} color="#3DD68C" />
            <StatCard label="Active jobs"     value={overview.jobs?.total}      sub={`${overview.jobs?.scraped} scraped`}          isDark={isDark} color="#F5A623" />
            <StatCard label="Applications"    value={overview.applications?.total} sub={`+${overview.applications?.last_7d} last 7d`} isDark={isDark} color="#9B59B6" />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            {/* Recent tenants */}
            <div style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "20px 22px" }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 14 }}>Recent tenants</div>
              {(overview.recent_tenants || []).map(t => (
                <div key={t.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0", borderBottom: isDark ? "1px solid #1e1e24" : "1px solid #f0f0f4" }}>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 500, color: isDark ? "#e0e0e0" : "#1d1d1f" }}>{t.name}</div>
                    <div style={{ fontSize: 11, color: isDark ? "#555" : "#aaa" }}>{t.slug}</div>
                  </div>
                  <span style={{ fontSize: 11, background: "rgba(0,113,227,0.1)", color: "#0071E3", padding: "2px 8px", borderRadius: 20 }}>{t.plan}</span>
                </div>
              ))}
            </div>

            {/* Top companies */}
            <div style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "20px 22px" }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 14 }}>Top hiring companies</div>
              {(overview.top_companies || []).map((c, i) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0", borderBottom: isDark ? "1px solid #1e1e24" : "1px solid #f0f0f4" }}>
                  <div style={{ fontSize: 13, color: isDark ? "#e0e0e0" : "#1d1d1f" }}>{c.company}</div>
                  <span style={{ fontSize: 12, fontWeight: 600, color: "#0071E3" }}>{c.job_count} jobs</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Tenants */}
      {tab === "tenants" && !loading && (
        <div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {tenants.map(t => (
              <div key={t.id} style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 12, padding: "14px 18px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f" }}>{t.name}</div>
                  <div style={{ fontSize: 12, color: isDark ? "#666" : "#888" }}>/{t.slug} · {t.country}</div>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <span style={{ fontSize: 11, background: "rgba(0,113,227,0.1)", color: "#0071E3", padding: "2px 10px", borderRadius: 20 }}>{t.plan}</span>
                  <span style={{ fontSize: 11, color: t.status === "active" ? "#3DD68C" : "#f87171", fontWeight: 600 }}>{t.status}</span>
                  <button
                    onClick={async () => {
                      await api(`/admin/tenants/${t.id}/status`, { method: "PATCH" });
                      setTenants(prev => prev.map(x => x.id === t.id ? { ...x, status: x.status === "active" ? "suspended" : "active" } : x));
                      toast("Status updated");
                    }}
                    style={{ fontSize: 11, background: "none", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 6, padding: "3px 10px", cursor: "pointer", color: isDark ? "#666" : "#555", fontFamily: "'DM Sans', sans-serif" }}
                  >
                    {t.status === "active" ? "Suspend" : "Activate"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Users */}
      {tab === "users" && !loading && (
        <div>
          {/* Search + filter bar */}
          <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
            <input value={userSearch} onChange={e => setUserSearch(e.target.value)}
              placeholder="Search name or email…"
              style={{ flex: 1, minWidth: 160, padding: "8px 12px", fontSize: 13, borderRadius: 8, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", background: isDark ? "#1a1a1e" : "#f8f8fb", color: isDark ? "#f0f0f2" : "#1d1d1f", fontFamily: "'DM Sans', sans-serif", outline: "none" }} />
            <select value={userRoleFilter} onChange={e => setUserRoleFilter(e.target.value)}
              style={{ padding: "8px 12px", fontSize: 13, borderRadius: 8, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", background: isDark ? "#1a1a1e" : "#f8f8fb", color: isDark ? "#f0f0f2" : "#1d1d1f", fontFamily: "'DM Sans', sans-serif", outline: "none", cursor: "pointer" }}>
              <option value="">All roles</option>
              {ALL_ROLES.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
            <span style={{ fontSize: 12, color: isDark ? "#555" : "#aaa" }}>
              {users.filter(u => (!userSearch || u.full_name?.toLowerCase().includes(userSearch.toLowerCase()) || u.email?.toLowerCase().includes(userSearch.toLowerCase())) && (!userRoleFilter || u.role === userRoleFilter)).length} users
            </span>
            <button onClick={() => setAddingUser(true)}
              style={{ background: "var(--btn-primary)", border: "none", borderRadius: 8, padding: "8px 14px", fontSize: 12, fontWeight: 600, color: "#fff", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", whiteSpace: "nowrap" }}>
              + Add user
            </button>
          </div>

          {/* Add user form */}
          {addingUser && (
            <div style={{ background: isDark ? "#1a1a1e" : "#f8f8fb", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 12, padding: "16px 20px", marginBottom: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 12 }}>Add new user</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto", gap: 8, alignItems: "end" }}>
                <input value={newUser.full_name} onChange={e => setNewUser(p => ({...p, full_name: e.target.value}))}
                  placeholder="Full name" style={{ padding: "8px 10px", fontSize: 12, borderRadius: 7, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", background: isDark ? "#141416" : "#fff", color: isDark ? "#f0f0f2" : "#1d1d1f", fontFamily: "'DM Sans', sans-serif", outline: "none" }} />
                <input value={newUser.email} onChange={e => setNewUser(p => ({...p, email: e.target.value}))}
                  placeholder="Email" type="email" style={{ padding: "8px 10px", fontSize: 12, borderRadius: 7, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", background: isDark ? "#141416" : "#fff", color: isDark ? "#f0f0f2" : "#1d1d1f", fontFamily: "'DM Sans', sans-serif", outline: "none" }} />
                <select value={newUser.role} onChange={e => setNewUser(p => ({...p, role: e.target.value}))}
                  style={{ padding: "8px 10px", fontSize: 12, borderRadius: 7, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", background: isDark ? "#141416" : "#fff", color: isDark ? "#f0f0f2" : "#1d1d1f", fontFamily: "'DM Sans', sans-serif", outline: "none", cursor: "pointer" }}>
                  {ALL_ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
                <button onClick={async () => {
                  if (!newUser.email || !newUser.full_name) { toast("Name and email required"); return; }
                  try {
                    const pwd = newUser.password || Math.random().toString(36).slice(-10);
                    await api("/admin/users", { method: "POST", body: JSON.stringify({...newUser, password: pwd}) });
                    toast(`User ${newUser.email} created`);
                    setAddingUser(false);
                    setNewUser({ full_name: "", email: "", password: "", role: "candidate", send_confirmation: true });
                    setUsers((await api("/admin/users?limit=100")).users || []);
                  } catch(e) { toast(e.message || "Failed to create user"); }
                }} style={{ background: "var(--btn-primary)", border: "none", borderRadius: 7, padding: "8px 12px", fontSize: 12, fontWeight: 600, color: "#fff", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", whiteSpace: "nowrap" }}>
                  Create
                </button>
              </div>
              <div style={{ marginTop: 8, display: "flex", gap: 16, alignItems: "center" }}>
                <input value={newUser.password} onChange={e => setNewUser(p => ({...p, password: e.target.value}))}
                  placeholder="Password (auto-generated if blank)" type="password"
                  style={{ flex: 1, padding: "7px 10px", fontSize: 12, borderRadius: 7, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", background: isDark ? "#141416" : "#fff", color: isDark ? "#f0f0f2" : "#1d1d1f", fontFamily: "'DM Sans', sans-serif", outline: "none" }} />
                <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: isDark ? "#aaa" : "#555", cursor: "pointer", whiteSpace: "nowrap" }}>
                  <input type="checkbox" checked={newUser.send_confirmation} onChange={e => setNewUser(p => ({...p, send_confirmation: e.target.checked}))} />
                  Send confirmation email
                </label>
                <button onClick={() => setAddingUser(false)} style={{ background: "none", border: "none", color: isDark ? "#555" : "#aaa", fontSize: 12, cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>Cancel</button>
              </div>
            </div>
          )}

          {/* User list */}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {users
              .filter(u =>
                (!userSearch || (u.full_name + " " + u.email).toLowerCase().includes(userSearch.toLowerCase())) &&
                (!userRoleFilter || u.role === userRoleFilter)
              )
              .map(u => (
              <div key={u.id} style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 12, padding: "12px 16px" }}>
                <div style={{ display: "flex", alignItems: "flex-start", gap: 10, flexWrap: "wrap" }}>
                  <div style={{ flex: 1, minWidth: 180 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f" }}>
                      {u.full_name || "No name"}
                      {u.is_online && <span style={{ marginLeft: 6, fontSize: 9, background: "#3DD68C", color: "#000", borderRadius: 4, padding: "1px 5px" }}>ONLINE</span>}
                    </div>
                    <div style={{ fontSize: 11, color: isDark ? "#555" : "#888", marginTop: 2 }}>{u.email}</div>
                    <div style={{ fontSize: 11, color: isDark ? "#444" : "#aaa", marginTop: 2 }}>
                      Last login: {u.last_login_at ? new Date(u.last_login_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "Never"}
                      {u.last_ip ? ` · IP: ${u.last_ip}` : ""}
                      {u.mfa_enabled ? " · 🔐 2FA on" : " · 2FA off"}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", flexShrink: 0 }}>
                    {/* Inline role assignment */}
                    <select
                      value={u.role || "candidate"}
                      onChange={async (e) => {
                        const newRole = e.target.value;
                        try {
                          await api(`/admin/users/${u.id}/role`, { method: "PATCH", body: JSON.stringify({ role: newRole }) });
                          setUsers(prev => prev.map(x => x.id === u.id ? { ...x, role: newRole } : x));
                          toast(`Role updated to ${newRole}`);
                        } catch(err) { toast(err.message || "Failed"); }
                      }}
                      style={{ fontSize: 11, padding: "3px 8px", borderRadius: 6, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", background: isDark ? "#1a1a1e" : "#f8f8fb", color: isDark ? "#f0f0f2" : "#1d1d1f", fontFamily: "'DM Sans', sans-serif", cursor: "pointer" }}
                    >
                      {ALL_ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                    </select>
                    <span style={{ fontSize: 11, fontWeight: 600, color: u.status === "active" ? "#3DD68C" : "#f87171" }}>{u.status}</span>
                    <button
                      onClick={async () => {
                        await api(`/admin/users/${u.id}/status`, { method: "PATCH" });
                        setUsers(prev => prev.map(x => x.id === u.id ? { ...x, status: x.status === "active" ? "suspended" : "active" } : x));
                        toast("Status updated");
                      }}
                      style={{ fontSize: 11, background: "none", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 6, padding: "3px 8px", cursor: "pointer", color: isDark ? "#666" : "#555", fontFamily: "'DM Sans', sans-serif" }}
                    >
                      {u.status === "active" ? "Suspend" : "Activate"}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Jobs */}
      {tab === "jobs" && !loading && (
        <div>
          {/* Search + filter bar */}
          <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap", alignItems: "center" }}>
            <input
              value={jobSearch}
              onChange={e => setJobSearch(e.target.value)}
              onKeyDown={e => e.key === "Enter" && loadTab("jobs")}
              placeholder="Search title or company…"
              style={{ flex: 1, minWidth: 180, padding: "8px 12px", fontSize: 13, borderRadius: 8, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", background: isDark ? "#1a1a1e" : "#f8f8fb", color: isDark ? "#f0f0f2" : "#1d1d1f", fontFamily: "'DM Sans', sans-serif", outline: "none" }}
            />
            <select value={jobStatusFilter} onChange={e => { setJobStatusFilter(e.target.value); loadTab("jobs"); }}
              style={{ padding: "8px 12px", fontSize: 13, borderRadius: 8, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", background: isDark ? "#1a1a1e" : "#f8f8fb", color: isDark ? "#f0f0f2" : "#1d1d1f", fontFamily: "'DM Sans', sans-serif", outline: "none", cursor: "pointer" }}>
              <option value="">All status</option>
              <option value="1">Published</option>
              <option value="0">Unpublished</option>
            </select>
            <button onClick={() => loadTab("jobs")}
              style={{ background: "var(--btn-primary)", border: "none", borderRadius: 8, padding: "8px 14px", fontSize: 12, fontWeight: 600, color: "#fff", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>
              Search
            </button>
            <span style={{ fontSize: 12, color: isDark ? "#555" : "#aaa" }}>{jobs.length} jobs</span>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {jobs.slice(jobPage * JOB_PAGE_SIZE, (jobPage + 1) * JOB_PAGE_SIZE).map(j => (
              <div key={j.id} style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 12, padding: "12px 16px", display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: 200 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f" }}>{j.title}</div>
                  <div style={{ fontSize: 11, color: isDark ? "#555" : "#aaa", marginTop: 2 }}>
                    {j.company} · {j.job_type} · {j.department}
                    {j.industry ? ` · 🏷 ${j.industry}` : ""}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, alignItems: "center", flexShrink: 0, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 11, fontWeight: 600, color: j.is_active ? "#3DD68C" : "#f87171" }}>
                    {j.is_active ? "Published" : "Unpublished"}
                  </span>
                  <button onClick={() => setEditingJob(j)}
                    style={{ fontSize: 11, background: "none", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 6, padding: "3px 10px", cursor: "pointer", color: isDark ? "#888" : "#555", fontFamily: "'DM Sans', sans-serif" }}>
                    ✏️ Edit
                  </button>
                  <button onClick={() => adminJobAction(j.is_active ? "unpublish" : "publish", j)}
                    style={{ fontSize: 11, background: j.is_active ? "rgba(245,166,35,0.1)" : "rgba(61,214,140,0.1)", border: j.is_active ? "1px solid rgba(245,166,35,0.3)" : "1px solid rgba(61,214,140,0.3)", borderRadius: 6, padding: "3px 10px", cursor: "pointer", color: j.is_active ? "#F5A623" : "#3DD68C", fontFamily: "'DM Sans', sans-serif" }}>
                    {j.is_active ? "⏸ Unpublish" : "▶ Publish"}
                  </button>
                  <button onClick={() => { if (window.confirm("Permanently delete this job and all its applications?")) adminJobAction("delete", j); }}
                    style={{ fontSize: 11, background: "rgba(245,101,101,0.1)", border: "1px solid rgba(245,101,101,0.3)", borderRadius: 6, padding: "3px 10px", cursor: "pointer", color: "#f87171", fontFamily: "'DM Sans', sans-serif" }}>
                    🗑 Delete
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/* Pagination */}
          {jobs.length > JOB_PAGE_SIZE && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 16, justifyContent: "center" }}>
              <button onClick={() => setJobPage(p => Math.max(0, p-1))} disabled={jobPage === 0}
                style={{ background: "none", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 7, padding: "6px 14px", fontSize: 12, color: isDark ? "#888" : "#555", cursor: jobPage === 0 ? "default" : "pointer", fontFamily: "'DM Sans', sans-serif", opacity: jobPage === 0 ? 0.4 : 1 }}>
                ← Prev
              </button>
              <span style={{ fontSize: 12, color: isDark ? "#555" : "#aaa" }}>
                Page {jobPage + 1} of {Math.ceil(jobs.length / JOB_PAGE_SIZE)} ({jobs.length} jobs)
              </span>
              <button onClick={() => setJobPage(p => p + 1)} disabled={(jobPage + 1) * JOB_PAGE_SIZE >= jobs.length}
                style={{ background: "none", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 7, padding: "6px 14px", fontSize: 12, color: isDark ? "#888" : "#555", cursor: (jobPage + 1) * JOB_PAGE_SIZE >= jobs.length ? "default" : "pointer", fontFamily: "'DM Sans', sans-serif", opacity: (jobPage + 1) * JOB_PAGE_SIZE >= jobs.length ? 0.4 : 1 }}>
                Next →
              </button>
            </div>
          )}
        </div>
      )}

      {/* Alerts monitoring */}
      {tab === "alerts" && !loading && (
        <div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
            <div style={{ fontSize: 12, color: isDark ? "#555" : "#aaa" }}>
              {alerts.length} alerts — open count updates when recipient clicks a job link
            </div>
            <button onClick={() => loadTab("alerts")}
              style={{ background: "none", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 7, padding: "5px 12px", fontSize: 11, color: isDark ? "#666" : "#555", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>
              ↺ Refresh
            </button>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {alerts.map(a => (
              <div key={a.id} style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 12, padding: "12px 16px", display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: 180 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f" }}>{a.keywords}</div>
                  <div style={{ fontSize: 11, color: isDark ? "#555" : "#aaa", marginTop: 2 }}>
                    {a.email} · {a.frequency} at {a.send_time}
                    {a.location ? ` · 📍 ${a.location}` : ""}
                    {a.industry ? ` · 🏷 ${a.industry}` : ""}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 16, fontSize: 12, flexShrink: 0 }}>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontWeight: 600, color: "#0071E3" }}>{a.emails_sent || 0}</div>
                    <div style={{ color: isDark ? "#555" : "#aaa", fontSize: 10 }}>Sent</div>
                  </div>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontWeight: 600, color: "#3DD68C" }}>{a.emails_opened || 0}</div>
                    <div style={{ color: isDark ? "#555" : "#aaa", fontSize: 10 }}>Opened</div>
                  </div>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontWeight: 600, color: a.emails_sent ? Math.round((a.emails_opened||0)/(a.emails_sent)*100) + "%" : "—", fontSize: 11 }}>
                      {a.emails_sent ? Math.round((a.emails_opened||0)/a.emails_sent*100) + "%" : "—"}
                    </div>
                    <div style={{ color: isDark ? "#555" : "#aaa", fontSize: 10 }}>Open rate</div>
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                  <span style={{ fontSize: 11, fontWeight: 600, color: a.is_active ? "#3DD68C" : "#f87171" }}>
                    {a.is_active ? "Active" : "Paused"}
                  </span>
                  <button
                    onClick={async () => {
                      try {
                        const res = await api(`/admin/alerts/${a.id}/send-now`, { method: "POST" });
                        toast(res.message || "Sent!");
                      } catch (e) { toast(e.message || "Send failed"); }
                    }}
                    style={{ fontSize: 11, background: "rgba(155,89,182,0.1)", border: "1px solid rgba(155,89,182,0.3)", borderRadius: 6, padding: "3px 8px", cursor: "pointer", color: "#9B59B6", fontFamily: "'DM Sans', sans-serif" }}
                  >
                    📧 Send now
                  </button>
                  <button
                    onClick={async () => {
                      await api(`/admin/alerts/${a.id}`, { method: "PATCH", body: JSON.stringify({ is_active: !a.is_active }) });
                      setAlerts(prev => prev.map(x => x.id === a.id ? { ...x, is_active: !x.is_active } : x));
                      toast("Alert updated");
                    }}
                    style={{ fontSize: 11, background: "none", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 6, padding: "3px 8px", cursor: "pointer", color: isDark ? "#666" : "#555", fontFamily: "'DM Sans', sans-serif" }}
                  >
                    {a.is_active ? "Pause" : "Resume"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Settings */}
      {tab === "settings" && !loading && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, alignItems: "start" }}>
          {/* Sidebar Nav Control — per user group */}
          <div style={{ gridColumn: "1 / -1", background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "20px 22px", marginBottom: 4 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 4 }}>Sidebar Menu Control</div>
            <div style={{ fontSize: 12, color: isDark ? "#555" : "#aaa", marginBottom: 16 }}>Choose which menu items each user type sees in the sidebar</div>
            <NavSettingsEditor isDark={isDark} toast={toast} />
          </div>

          {/* Email template editor — FIRST */}
          <EmailTemplateEditor isDark={isDark} template={template} setTemplate={setTemplate}
            templateDirty={templateDirty} setTemplateDirty={setTemplateDirty}
            saveTemplate={saveTemplate} resetTemplate={resetTemplate} toast={toast} user={user} />



          {/* Brand Settings */}
          <div style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "20px 22px" }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 4 }}>Brand Settings</div>
            <div style={{ fontSize: 12, color: isDark ? "#555" : "#aaa", marginBottom: 16 }}>Customise the platform name and logo shown to all users</div>
            <div style={{ marginBottom: 12 }}>
              <label style={{ fontSize: 11, fontWeight: 600, color: isDark ? "#666" : "#888", textTransform: "uppercase", letterSpacing: "0.4px", display: "block", marginBottom: 5 }}>Platform name</label>
              <input value={brandSettings.name || ""} onChange={e => { setBrandSettings(p => ({...p, name: e.target.value})); setBrandDirty(true); }}
                placeholder="JobStream"
                style={{ width: "100%", boxSizing: "border-box", padding: "8px 12px", fontSize: 13, borderRadius: 8, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", background: isDark ? "#141416" : "#fff", color: isDark ? "#f0f0f2" : "#1d1d1f", fontFamily: "'DM Sans', sans-serif", outline: "none" }} />
            </div>
            <div style={{ marginBottom: 14 }}>
              <label style={{ fontSize: 11, fontWeight: 600, color: isDark ? "#666" : "#888", textTransform: "uppercase", letterSpacing: "0.4px", display: "block", marginBottom: 5 }}>Logo URL</label>
              <input value={brandSettings.logo_url || ""} onChange={e => { setBrandSettings(p => ({...p, logo_url: e.target.value})); setBrandDirty(true); }}
                placeholder="https://your-domain.com/logo.png"
                style={{ width: "100%", boxSizing: "border-box", padding: "8px 12px", fontSize: 13, borderRadius: 8, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", background: isDark ? "#141416" : "#fff", color: isDark ? "#f0f0f2" : "#1d1d1f", fontFamily: "'DM Sans', sans-serif", outline: "none" }} />
              {brandSettings.logo_url && (
                <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 10 }}>
                  <img src={brandSettings.logo_url} alt="preview" style={{ height: 36, objectFit: "contain", borderRadius: 6, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", padding: 4 }} onError={e => e.target.style.display = "none"} />
                  <span style={{ fontSize: 11, color: isDark ? "#555" : "#aaa" }}>Logo preview</span>
                </div>
              )}
            </div>
            <button onClick={async () => {
              try {
                await api("/admin/settings/brand", { method: "POST", body: JSON.stringify(brandSettings) });
                setBrandDirty(false);
                toast("Brand settings saved — reload to see changes");
              } catch(e) { toast(e.message || "Failed"); }
            }} disabled={!brandDirty}
              style={{ background: brandDirty ? "#0071E3" : (isDark ? "#222" : "#ddd"), border: "none", borderRadius: 8, padding: "7px 16px", fontSize: 12, fontWeight: 600, color: brandDirty ? "#fff" : (isDark ? "#444" : "#aaa"), cursor: brandDirty ? "pointer" : "default", fontFamily: "'DM Sans', sans-serif" }}>
              {brandDirty ? "Save brand" : "✓ Saved"}
            </button>
          </div>

          {/* Streamer Control */}
          <div style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "20px 22px" }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 4 }}>Streamer Settings</div>
            <div style={{ fontSize: 12, color: isDark ? "#555" : "#aaa", marginBottom: 16 }}>Control how often the streamer automatically fetches new jobs</div>

            <label style={{ fontSize: 11, fontWeight: 600, color: isDark ? "#666" : "#888", textTransform: "uppercase", letterSpacing: "0.4px", display: "block", marginBottom: 6 }}>Run every (hours)</label>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 16 }}>
              <input type="number" min="1" max="168" value={streamerHours}
                onChange={e => { setStreamerHours(Number(e.target.value)); setStreamerDirty(true); }}
                style={{ width: 80, padding: "7px 10px", fontSize: 13, borderRadius: 7, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", background: isDark ? "#141416" : "#fff", color: isDark ? "#f0f0f2" : "#1d1d1f", fontFamily: "'DM Sans', sans-serif", outline: "none" }} />
              <span style={{ fontSize: 12, color: isDark ? "#555" : "#aaa" }}>
                {streamerHours === 1 ? "hour" : "hours"} (1–168). Currently: every {streamerHours}h. Restart backend to apply.
              </span>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button onClick={async () => {
                try {
                  const res = await api("/admin/settings/streamer", { method: "POST", body: JSON.stringify({ scrape_interval_hours: streamerHours }) });
                  setStreamerDirty(false);
                  toast(res.message || "Saved");
                } catch(e) { toast(e.message || "Failed"); }
              }} disabled={!streamerDirty}
                style={{ background: streamerDirty ? "#0071E3" : (isDark ? "#222" : "#ddd"), border: "none", borderRadius: 8, padding: "7px 16px", fontSize: 12, fontWeight: 600, color: streamerDirty ? "#fff" : (isDark ? "#444" : "#aaa"), cursor: streamerDirty ? "pointer" : "default", fontFamily: "'DM Sans', sans-serif" }}>
                {streamerDirty ? "Save interval" : "✓ Saved"}
              </button>
            </div>

            <div style={{ borderTop: isDark ? "1px solid #1e1e24" : "1px solid #f0f0f4", marginTop: 16, paddingTop: 16 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: isDark ? "#aaa" : "#555", marginBottom: 8 }}>Backfill company industry to existing jobs</div>
              <div style={{ fontSize: 11, color: isDark ? "#555" : "#aaa", marginBottom: 10 }}>
                Run this once after setting industries on companies. Updates all existing jobs that have no industry.
              </div>
              <button onClick={async () => {
                setBackfillingInd(true);
                try {
                  const res = await api("/jobs/backfill-industry", { method: "POST" });
                  toast(res.message || "Done");
                } catch(e) { toast(e.message || "Failed"); }
                finally { setBackfillingInd(false); }
              }} disabled={backfilling}
                style={{ background: backfilling ? (isDark ? "#222" : "#ddd") : "#3DD68C", border: "none", borderRadius: 8, padding: "7px 16px", fontSize: 12, fontWeight: 600, color: backfilling ? (isDark ? "#555" : "#aaa") : "#000", cursor: backfilling ? "default" : "pointer", fontFamily: "'DM Sans', sans-serif" }}>
                {backfilling ? "Running…" : "🏷 Backfill industry to jobs"}
              </button>
            </div>
          </div>

          {/* Theme Colors — appears above industry list */}
          <div style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "20px 22px" }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 4 }}>Frontend Theme</div>
            <div style={{ fontSize: 12, color: isDark ? "#555" : "#aaa", marginBottom: 16 }}>Customise the app accent and background colours for all users</div>
            {[
              { key: "accent_color",       label: "Link / highlight colour" },
              { key: "btn_color_dark",     label: "Button colour (dark mode)" },
              { key: "btn_color_light",    label: "Button colour (light mode)" },
              { key: "bg_dark",            label: "Dark mode background" },
              { key: "bg_light",           label: "Light mode background" },
            ].map(({ key, label }) => (
              <div key={key} style={{ marginBottom: 12 }}>
                <label style={{ fontSize: 11, fontWeight: 600, color: isDark ? "#666" : "#888", textTransform: "uppercase", letterSpacing: "0.4px", display: "block", marginBottom: 5 }}>{label}</label>
                <div style={{ display: "flex", gap: 8 }}>
                  <input type="color" value={themeSettings[key] || "#000000"}
                    onChange={e => { setThemeSettings(p => ({...p, [key]: e.target.value})); setThemeDirty(true); }}
                    style={{ width: 36, height: 32, border: "none", borderRadius: 6, cursor: "pointer", padding: 0 }} />
                  <input value={themeSettings[key] || ""}
                    onChange={e => { setThemeSettings(p => ({...p, [key]: e.target.value})); setThemeDirty(true); }}
                    style={{ flex: 1, padding: "7px 10px", fontSize: 12, borderRadius: 7, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", background: isDark ? "#141416" : "#fff", color: isDark ? "#f0f0f2" : "#1d1d1f", fontFamily: "'DM Sans', sans-serif", outline: "none" }} />
                </div>
              </div>
            ))}
            <button onClick={async () => {
              try {
                await api("/admin/settings/theme", { method: "POST", body: JSON.stringify(themeSettings) });
                setThemeDirty(false);
                toast("Theme saved — reload to see changes");
              } catch(e) { toast(e.message || "Failed"); }
            }} disabled={!themeDirty}
              style={{ marginTop: 4, background: themeDirty ? "#0071E3" : (isDark ? "#222" : "#ddd"), border: "none", borderRadius: 8, padding: "7px 16px", fontSize: 12, fontWeight: 600, color: themeDirty ? "#fff" : (isDark ? "#444" : "#aaa"), cursor: themeDirty ? "pointer" : "default", fontFamily: "'DM Sans', sans-serif" }}>
              {themeDirty ? "Save theme" : "✓ Saved"}
            </button>
          </div>

          {/* Industry list manager — SECOND */}
          <div style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "20px 22px" }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 4 }}>Industry List</div>
            <div style={{ fontSize: 12, color: isDark ? "#555" : "#aaa", marginBottom: 16 }}>Add or remove industries available in job alerts and streamer config</div>
            <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
              <input value={newIndustry} onChange={e => setNewIndustry(e.target.value)}
                placeholder="e.g. General, Aviation..."
                onKeyDown={e => e.key === "Enter" && addIndustry()}
                style={{ flex: 1, padding: "8px 12px", fontSize: 13, borderRadius: 8, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", background: isDark ? "#1a1a1e" : "#f8f8fb", color: isDark ? "#f0f0f2" : "#1d1d1f", fontFamily: "'DM Sans', sans-serif", outline: "none" }} />
              <button onClick={addIndustry} style={{ background: "var(--btn-primary)", border: "none", borderRadius: 8, padding: "8px 14px", fontSize: 13, color: "#fff", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>+ Add</button>
            </div>
            <div style={{ maxHeight: 300, overflowY: "auto", display: "flex", flexDirection: "column", gap: 4 }}>
              {industries.map(ind => (
                <div key={ind} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 10px", background: isDark ? "#1a1a1e" : "#f8f8fb", borderRadius: 8 }}>
                  <span style={{ fontSize: 13, color: isDark ? "#ccc" : "#333" }}>{ind}</span>
                  <button onClick={() => removeIndustry(ind)}
                    style={{ background: "none", border: "none", color: "#f87171", cursor: "pointer", fontSize: 14, padding: "0 4px" }}>✕</button>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Job edit modal */}
      {editingJob && <AdminJobEditModal job={editingJob} isDark={isDark} onSave={saveJobEdit} onClose={() => setEditingJob(null)} jobTypes={JOB_TYPES} departments={DEPARTMENTS} industries={industries} />}
    </div>
  );
}


// ── Admin Job Edit Modal ──────────────────────────────────────────────────────
function AdminJobEditModal({ job, isDark, onSave, onClose, jobTypes, departments, industries }) {
  const [title, setTitle] = useState(job.title || "");
  const [jobType, setJobType] = useState(job.job_type || "Full-time");
  const [department, setDepartment] = useState(job.department || "General");
  const [industry, setIndustry] = useState(job.industry || "");
  const [location, setLocation] = useState(job.location || "");
  // Load existing description — admin can see and edit the full scraped text
  const [description, setDescription] = useState(job.description || "");
  const [saving, setSaving] = useState(false);
  const [descChars, setDescChars] = useState((job.description || "").length);

  const inp = { width: "100%", boxSizing: "border-box", padding: "9px 12px", fontSize: 13, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 8, background: isDark ? "#1a1a1e" : "#ffffff", color: isDark ? "#f0f0f2" : "#1d1d1f", fontFamily: "'DM Sans', sans-serif", outline: "none" };
  const lbl = { fontSize: 11, fontWeight: 600, color: isDark ? "#888" : "#555", textTransform: "uppercase", letterSpacing: "0.5px", display: "block", marginBottom: 5 };

  async function handleSave() {
    setSaving(true);
    await onSave({ title, job_type: jobType, department, industry, location, description });
    setSaving(false);
  }

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)", backdropFilter: "blur(4px)", display: "flex", alignItems: "stretch", justifyContent: "center", zIndex: 9999, padding: "20px" }}>
      <div onClick={e => e.stopPropagation()} style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 16, width: "100%", maxWidth: 900, display: "flex", flexDirection: "column", overflow: "hidden" }}>

        {/* Header */}
        <div style={{ padding: "20px 28px 16px", borderBottom: isDark ? "1px solid #1e1e24" : "1px solid #f0f0f4", display: "flex", justifyContent: "space-between", alignItems: "center", flexShrink: 0 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f" }}>✏️ Edit Job</div>
            <div style={{ fontSize: 11, color: isDark ? "#555" : "#aaa", marginTop: 2 }}>{job.company} · ID {job.id}</div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={onClose} style={{ background: "none", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 8, padding: "8px 16px", fontSize: 13, color: isDark ? "#888" : "#555", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>Cancel</button>
            <button onClick={handleSave} disabled={saving} style={{ background: "var(--btn-primary)", border: "none", borderRadius: 8, padding: "8px 18px", fontSize: 13, fontWeight: 600, color: "#fff", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", opacity: saving ? 0.7 : 1 }}>
              {saving ? "Saving…" : "Save changes"}
            </button>
          </div>
        </div>

        {/* Body — split: metadata left, description right */}
        <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", flex: 1, overflow: "hidden" }}>

          {/* Left: metadata fields */}
          <div style={{ padding: "20px 24px", overflowY: "auto", borderRight: isDark ? "1px solid #1e1e24" : "1px solid #f0f0f4" }}>
            <div style={{ marginBottom: 14 }}>
              <label style={lbl}>Job Title</label>
              <input value={title} onChange={e => setTitle(e.target.value)} style={inp} />
            </div>
            <div style={{ marginBottom: 14 }}>
              <label style={lbl}>Location</label>
              <input value={location} onChange={e => setLocation(e.target.value)} style={inp} />
            </div>
            <div style={{ marginBottom: 14 }}>
              <label style={lbl}>Job Type</label>
              <select value={jobType} onChange={e => setJobType(e.target.value)} style={{ ...inp, cursor: "pointer" }}>
                {jobTypes.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div style={{ marginBottom: 14 }}>
              <label style={lbl}>Department</label>
              <select value={department} onChange={e => setDepartment(e.target.value)} style={{ ...inp, cursor: "pointer" }}>
                {departments.map(d => <option key={d} value={d}>{d}</option>)}
              </select>
            </div>
            <div style={{ marginBottom: 14 }}>
              <label style={lbl}>Industry</label>
              <select value={industry} onChange={e => setIndustry(e.target.value)} style={{ ...inp, cursor: "pointer" }}>
                <option value="">None</option>
                {industries.map(i => <option key={i} value={i}>{i}</option>)}
              </select>
            </div>
            <div style={{ background: isDark ? "#1a1a1e" : "#f8f8fb", borderRadius: 8, padding: "12px 14px", fontSize: 11, color: isDark ? "#555" : "#aaa", lineHeight: 1.6 }}>
              <div style={{ fontWeight: 600, color: isDark ? "#666" : "#888", marginBottom: 4 }}>Description formatting</div>
              <code style={{ color: "#0071E3" }}>**Heading**</code> → bold heading<br />
              <code style={{ color: "#0071E3" }}>• Item</code> → bullet point<br />
              Edit the text directly to correct errors from the source.
            </div>
          </div>

          {/* Right: description editor */}
          <div style={{ display: "flex", flexDirection: "column", padding: "20px 24px", overflow: "hidden" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <label style={lbl}>Job Description</label>
              <span style={{ fontSize: 11, color: isDark ? "#444" : "#bbb" }}>{descChars} chars</span>
            </div>
            <textarea
              value={description}
              onChange={e => { setDescription(e.target.value); setDescChars(e.target.value.length); }}
              style={{
                flex: 1, width: "100%", boxSizing: "border-box",
                padding: "12px 14px", fontSize: 13, lineHeight: 1.8,
                border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8",
                borderRadius: 8, resize: "none",
                background: isDark ? "#0d0d0f" : "#fafafa",
                color: isDark ? "#e0e0e0" : "#1d1d1f",
                fontFamily: "'DM Mono', monospace",
                outline: "none",
                minHeight: 400,
              }}
            />
            {!description && (
              <div style={{ fontSize: 12, color: "#f87171", marginTop: 6 }}>
                ⚠ No description available for this job yet. Paste or type the description above.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}


// ── Workspace Dashboard Page ──────────────────────────────────────────────────
function WorkspaceDashboardPage({ isDark = true, user, onAuthRequired, toast }) {
  const [overview, setOverview] = useState(null);
  const [pipeline, setPipeline] = useState(null);
  const [team, setTeam] = useState([]);
  const [tab, setTab] = useState("overview");
  const [loading, setLoading] = useState(true);

  const isOrgAdmin = user && ["super_admin", "platform_admin", "org_owner", "hr_admin"].includes(user.role);

  useEffect(() => {
    if (!user?.tenant_id) return;
    api("/workspace/overview").then(setOverview).catch(() => {}).finally(() => setLoading(false));
  }, [user]);

  async function loadTab(t) {
    setTab(t); setLoading(true);
    try {
      if (t === "pipeline") setPipeline((await api("/workspace/pipeline")).pipeline || {});
      if (t === "team")     setTeam(await api("/workspace/team"));
    } catch { toast("Failed to load"); }
    finally { setLoading(false); }
  }

  if (!user) return (
    <div style={{ textAlign: "center", padding: 60 }}>
      <div style={{ fontSize: 40, marginBottom: 16 }}>🏢</div>
      <div style={{ fontSize: 14, color: isDark ? "#666" : "#888", marginBottom: 24 }}>Sign in to access your workspace</div>
      <button onClick={onAuthRequired} style={{ background: "var(--btn-primary)", color: "#fff", border: "none", borderRadius: 10, padding: "10px 24px", fontSize: 14, fontWeight: 600, cursor: "pointer" }}>Sign in</button>
    </div>
  );

  if (!user.tenant_id) return (
    <div style={{ textAlign: "center", padding: 60 }}>
      <div style={{ fontSize: 40, marginBottom: 16 }}>🏢</div>
      <div style={{ fontSize: 16, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 8 }}>No workspace yet</div>
      <div style={{ fontSize: 13, color: isDark ? "#666" : "#888" }}>Go to the Employer page to create your workspace first</div>
    </div>
  );

  const tabs = [
    { id: "overview",  label: "Overview"  },
    { id: "pipeline",  label: "Pipeline"  },
    { id: "team",      label: "Team"      },
  ];

  const stageColors = { new: "#0071E3", reviewing: "#F5A623", shortlisted: "#9B59B6", interview: "#E67E22", offer: "#2ECC71", hired: "#27AE60", rejected: "#f87171" };

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", letterSpacing: -0.5, marginBottom: 4 }}>Workspace Dashboard</h1>
        <p style={{ fontSize: 13, color: isDark ? "#666" : "#888" }}>Your hiring pipeline and team overview</p>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 24 }}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => loadTab(t.id)} style={{ background: tab === t.id ? "#0071E3" : "none", border: tab === t.id ? "none" : isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 8, padding: "7px 16px", fontSize: 13, color: tab === t.id ? "#fff" : isDark ? "#888" : "#555", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", fontWeight: tab === t.id ? 600 : 400 }}>{t.label}</button>
        ))}
      </div>

      {loading && <Spinner />}

      {/* Overview */}
      {tab === "overview" && overview && !loading && (
        <div>
          <div style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap" }}>
            <StatCard label="Active jobs"      value={overview.jobs?.active}           isDark={isDark} />
            <StatCard label="Total applicants" value={overview.applications?.total}    isDark={isDark} color="#F5A623" sub={`+${overview.applications?.new_7d} this week`} />
            <StatCard label="Hired"            value={overview.hiring?.hired}          isDark={isDark} color="#3DD68C" sub={`${overview.hiring?.offer_rate}% offer rate`} />
            <StatCard label="Team members"     value={overview.team?.members}          isDark={isDark} color="#9B59B6" />
          </div>

          {/* Applications by status */}
          <div style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "20px 22px", marginBottom: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 14 }}>Applications by stage</div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {(overview.applications?.by_status || []).map(s => (
                <div key={s.status} style={{ textAlign: "center", minWidth: 80 }}>
                  <div style={{ fontSize: 22, fontWeight: 700, color: stageColors[s.status] || "#888" }}>{s.count}</div>
                  <div style={{ fontSize: 11, color: isDark ? "#666" : "#aaa", textTransform: "capitalize" }}>{s.status}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Top jobs */}
          <div style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "20px 22px" }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 14 }}>Top jobs by applications</div>
            {(overview.top_jobs || []).map(j => (
              <div key={j.id} style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: isDark ? "1px solid #1e1e24" : "1px solid #f0f0f4" }}>
                <div style={{ fontSize: 13, color: isDark ? "#e0e0e0" : "#1d1d1f" }}>{j.title}</div>
                <span style={{ fontSize: 12, fontWeight: 600, color: "#0071E3" }}>{j.app_count} apps</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Pipeline */}
      {tab === "pipeline" && pipeline && !loading && (
        <div style={{ display: "flex", gap: 12, overflowX: "auto", paddingBottom: 8 }}>
          {Object.entries(pipeline).map(([stage, apps]) => (
            <div key={stage} style={{ minWidth: 220, flex: "0 0 220px" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: stageColors[stage] || "#888", textTransform: "capitalize" }}>{stage}</span>
                <span style={{ fontSize: 11, color: isDark ? "#555" : "#aaa" }}>{apps.length}</span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {apps.map(a => (
                  <div key={a.id} style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 10, padding: "12px 14px" }}>
                    <div style={{ fontSize: 13, fontWeight: 500, color: isDark ? "#e0e0e0" : "#1d1d1f", marginBottom: 2 }}>{a.name}</div>
                    <div style={{ fontSize: 11, color: isDark ? "#555" : "#aaa" }}>{a.job_title}</div>
                  </div>
                ))}
                {apps.length === 0 && <div style={{ fontSize: 12, color: isDark ? "#444" : "#ccc", textAlign: "center", padding: 20 }}>Empty</div>}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Team */}
      {tab === "team" && !loading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {team.map(m => (
            <div key={m.id} style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 12, padding: "14px 18px", display: "flex", alignItems: "center", gap: 14 }}>
              <div style={{ width: 36, height: 36, borderRadius: "50%", background: "var(--btn-primary)", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, fontWeight: 700, flexShrink: 0 }}>
                {(m.full_name || m.email || "?")[0].toUpperCase()}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 14, fontWeight: 500, color: isDark ? "#f0f0f2" : "#1d1d1f" }}>{m.full_name || "No name"}</div>
                <div style={{ fontSize: 12, color: isDark ? "#666" : "#888" }}>{m.email}</div>
              </div>
              <span style={{ fontSize: 11, color: isDark ? "#666" : "#888", textTransform: "capitalize" }}>{m.role}</span>
            </div>
          ))}
          {team.length === 0 && <div style={{ textAlign: "center", padding: 40, color: isDark ? "#555" : "#aaa", fontSize: 13 }}>No team members yet. Invite from the Employer page.</div>}
        </div>
      )}
    </div>
  );
}


// ── Job Slug Handler ─────────────────────────────────────────────────────────
function JobSlugHandler({ slug, isDark, user, onAuthRequired, toast, onClose }) {
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    api(`/jobs/by-slug/${slug}`)
      .then(setJob)
      .catch(() => setError("Job not found"))
      .finally(() => setLoading(false));
  }, [slug]);

  // Inject JSON-LD for SEO
  useEffect(() => {
    if (!job) return;
    const existing = document.getElementById("job-jsonld");
    if (existing) existing.remove();
    api(`/jobs/${job.id}/structured-data`)
      .then(data => {
        const script = document.createElement("script");
        script.id = "job-jsonld";
        script.type = "application/ld+json";
        script.textContent = JSON.stringify(data);
        document.head.appendChild(script);
      })
      .catch(() => {});
    return () => { const el = document.getElementById("job-jsonld"); if (el) el.remove(); };
  }, [job]);

  if (loading) return <Spinner />;
  if (error || !job) return null;

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 8000, padding: 20 }}>
      <div onClick={e => e.stopPropagation()} style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 20, width: "100%", maxWidth: 680, maxHeight: "90vh", overflowY: "auto", padding: "28px 32px" }}>
        <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: isDark ? "#666" : "#888", fontSize: 13, fontFamily: "'DM Sans', sans-serif", marginBottom: 20, padding: 0 }}>← Back</button>
        <JobCard job={job} onApply={() => {}} onView={() => {}} isExpanded={true} isDark={isDark} user={user} onAuthRequired={onAuthRequired} isSaved={false} onToggleSave={() => {}} />
      </div>
    </div>
  );
}


// ── Org Slug Handler ──────────────────────────────────────────────────────────
function OrgSlugHandler({ slug, isDark, onBack, onApply, user, onAuthRequired, toast }) {
  const [org, setOrg] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api(`/organizations/by-slug/${slug}`)
      .then(setOrg)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [slug]);

  if (loading) return <Spinner />;
  if (!org) return null;

  return (
    <CompanyProfilePage
      isDark={isDark}
      companyId={org.id}
      onApply={onApply}
      user={user}
      onAuthRequired={onAuthRequired}
      onBack={onBack}
      toast={toast}
    />
  );
}


// ── Job Alerts Modal ──────────────────────────────────────────────────────────
function JobAlertsModal({ isDark = true, onClose, toast, user, existingAlert = null }) {
  const isEdit = !!existingAlert;
  const [email, setEmail] = useState(user?.email || "");
  const [keywords, setKeywords] = useState(existingAlert?.keywords || "");
  const [location, setLocation] = useState(existingAlert?.location || "");
  const [industry, setIndustry] = useState(existingAlert?.industry || "");
  const [frequency, setFrequency] = useState(existingAlert?.frequency || "daily");
  const [sendTime, setSendTime] = useState(existingAlert?.send_time || "08:00");
  const [timezone, setTimezone] = useState(existingAlert?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || "Africa/Lagos");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const [meta, setMeta] = useState({ industries: [], send_times: ["06:00","08:00","12:00","17:00","20:00"] });

  // Simple math captcha for guests
  const [captchaA, setCaptchaA] = useState(() => Math.floor(Math.random() * 8) + 1);
  const [captchaB, setCaptchaB] = useState(() => Math.floor(Math.random() * 8) + 1);
  const [captchaAnswer, setCaptchaAnswer] = useState("");

  const inp = { width: "100%", boxSizing: "border-box", padding: "10px 14px", fontSize: 13, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 10, background: isDark ? "#141416" : "#ffffff", color: isDark ? "#f0f0f2" : "#1d1d1f", fontFamily: "'DM Sans', sans-serif", outline: "none" };
  const lbl = { fontSize: 11, fontWeight: 600, color: isDark ? "#888" : "#555", textTransform: "uppercase", letterSpacing: "0.5px", display: "block", marginBottom: 6 };

  useEffect(() => {
    api("/job-alerts/meta").then(setMeta).catch(() => {});
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");

    if (!user && !email.trim()) {
      setError("Email is required.");
      return;
    }
    if (!user && Number(captchaAnswer) !== captchaA + captchaB) {
      setError("Captcha answer is incorrect. Please try again.");
      setCaptchaA(Math.floor(Math.random() * 8) + 1);
      setCaptchaB(Math.floor(Math.random() * 8) + 1);
      setCaptchaAnswer("");
      return;
    }

    setLoading(true);
    try {
      const payload = {
        email, keywords, location, industry, frequency, send_time: sendTime, timezone,
        ...(!user ? { captcha_answer: Number(captchaAnswer), captcha_expected: captchaA + captchaB } : {}),
      };
      if (isEdit) {
        await api(`/job-alerts/${existingAlert.id}`, { method: "PATCH", body: JSON.stringify(payload) });
        toast && toast("Alert updated!");
        onClose(true);
        return;
      }
      await api("/job-alerts", { method: "POST", body: JSON.stringify(payload) });
      setDone(true);
      toast && toast("Job alert created!");
    } catch (e) {
      setError(e.message || "Failed to save alert");
    } finally { setLoading(false); }
  }

  return (
    <div onClick={() => onClose(false)} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 9000, padding: 20 }}>
      <div onClick={e => e.stopPropagation()} style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 20, width: "100%", maxWidth: 440, padding: "32px 28px", maxHeight: "90vh", overflowY: "auto" }}>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 6 }}>🔔 {isEdit ? "Edit Job Alert" : "Job Alerts"}</h2>
        <p style={{ fontSize: 13, color: isDark ? "#666" : "#888", marginBottom: 24 }}>Get notified by email when new matching jobs are posted.</p>

        {error && (
          <div style={{ background: "rgba(245,101,101,0.1)", border: "1px solid rgba(245,101,101,0.3)", borderRadius: 8, padding: "10px 14px", marginBottom: 16, fontSize: 13, color: "#f87171" }}>{error}</div>
        )}

        {done ? (
          <div style={{ textAlign: "center", padding: "20px 0" }}>
            <div style={{ fontSize: 36, marginBottom: 12 }}>✅</div>
            <div style={{ fontSize: 15, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 8 }}>Alert created!</div>
            <div style={{ fontSize: 13, color: isDark ? "#666" : "#888", marginBottom: 20 }}>
              You'll get {frequency} emails at {sendTime} for "{keywords}"{location ? ` in ${location}` : ""}
              {industry ? ` (${industry})` : ""}.
              {user && " Manage it anytime from your profile menu → My Alerts."}
            </div>
            <button onClick={() => onClose(true)} style={{ background: "var(--btn-primary)", border: "none", borderRadius: 10, padding: "10px 24px", fontSize: 13, fontWeight: 600, color: "#fff", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>Done</button>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            {!user && (
              <div style={{ marginBottom: 14 }}>
                <label style={lbl}>Email</label>
                <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@email.com" required style={inp} />
              </div>
            )}

            <div style={{ marginBottom: 14 }}>
              <label style={lbl}>Job titles / keywords</label>
              <input value={keywords} onChange={e => setKeywords(e.target.value)} placeholder="Software Engineer, Network Engineer, Accountant" required style={inp} />
              <div style={{ fontSize: 11, color: isDark ? "#555" : "#aaa", marginTop: 4 }}>Job titles or skills relating to your profession — comma separated</div>
            </div>

            <div style={{ marginBottom: 14 }}>
              <label style={lbl}>Location (optional)</label>
              <input value={location} onChange={e => setLocation(e.target.value)} placeholder="e.g. Lagos, Nigeria, Remote, or leave blank for any location" style={inp} />
              <div style={{ fontSize: 11, color: isDark ? "#555" : "#aaa", marginTop: 4 }}>Leave blank to get alerts for any location, or specify "Remote"</div>
            </div>

            <div style={{ marginBottom: 14 }}>
              <label style={lbl}>Industry (optional)</label>
              <select value={industry} onChange={e => setIndustry(e.target.value)} style={{ ...inp, cursor: "pointer" }}>
                <option value="">Any industry</option>
                {(meta.industries || []).map(ind => <option key={ind} value={ind}>{ind}</option>)}
              </select>
              <div style={{ fontSize: 11, color: isDark ? "#555" : "#aaa", marginTop: 4 }}>e.g. Telecommunications, Banking &amp; Finance</div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
              <div>
                <label style={lbl}>Frequency</label>
                <select value={frequency} onChange={e => setFrequency(e.target.value)} style={{ ...inp, cursor: "pointer" }}>
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                </select>
              </div>
              <div>
                <label style={lbl}>Preferred time</label>
                <select value={sendTime} onChange={e => setSendTime(e.target.value)} style={{ ...inp, cursor: "pointer" }}>
                  {(meta.send_times || ["06:00","08:00","12:00","17:00","20:00"]).map(t => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <label style={lbl}>Timezone</label>
                <select value={timezone} onChange={e => setTimezone(e.target.value)} style={{ ...inp, cursor: "pointer" }}>
                  {[
                    ["Africa/Lagos",       "Lagos (WAT UTC+1)"],
                    ["Africa/Accra",       "Accra (GMT UTC+0)"],
                    ["Africa/Nairobi",     "Nairobi (EAT UTC+3)"],
                    ["Africa/Johannesburg","Johannesburg (SAST UTC+2)"],
                    ["Africa/Cairo",       "Cairo (EET UTC+2)"],
                    ["Africa/Casablanca",  "Casablanca (WET UTC+0)"],
                    ["Europe/London",      "London (GMT/BST)"],
                    ["Europe/Paris",       "Paris (CET UTC+1)"],
                    ["Europe/Berlin",      "Berlin (CET UTC+1)"],
                    ["Europe/Moscow",      "Moscow (MSK UTC+3)"],
                    ["Asia/Dubai",         "Dubai (GST UTC+4)"],
                    ["Asia/Kolkata",       "India (IST UTC+5:30)"],
                    ["Asia/Singapore",     "Singapore (SGT UTC+8)"],
                    ["Asia/Tokyo",         "Tokyo (JST UTC+9)"],
                    ["Asia/Shanghai",      "China (CST UTC+8)"],
                    ["Australia/Sydney",   "Sydney (AEDT UTC+11)"],
                    ["Pacific/Auckland",   "Auckland (NZDT UTC+13)"],
                    ["America/New_York",   "New York (ET UTC-5)"],
                    ["America/Chicago",    "Chicago (CT UTC-6)"],
                    ["America/Denver",     "Denver (MT UTC-7)"],
                    ["America/Los_Angeles","Los Angeles (PT UTC-8)"],
                    ["America/Sao_Paulo",  "São Paulo (BRT UTC-3)"],
                    ["America/Toronto",    "Toronto (ET UTC-5)"],
                  ].map(([tz, label]) => <option key={tz} value={tz}>{label}</option>)}
                </select>
              </div>
            </div>

            {!user && (
              <div style={{ marginBottom: 14, background: isDark ? "#1a1a1e" : "#f8f8fb", borderRadius: 10, padding: "12px 14px" }}>
                <label style={lbl}>Quick check — what is {captchaA} + {captchaB}?</label>
                <input
                  type="number" value={captchaAnswer}
                  onChange={e => setCaptchaAnswer(e.target.value)}
                  placeholder="Your answer" required
                  style={inp}
                />
                <div style={{ fontSize: 11, color: isDark ? "#555" : "#aaa", marginTop: 4 }}>This helps us prevent spam sign-ups</div>
              </div>
            )}

            {user && (
              <div style={{ fontSize: 11, color: isDark ? "#555" : "#aaa", marginBottom: 14 }}>
                Alerts will be sent to <strong>{user.email}</strong> and can be managed anytime from your profile menu → My Alerts.
              </div>
            )}

            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button type="button" onClick={() => onClose(false)} style={{ background: "none", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 10, padding: "10px 20px", fontSize: 13, color: isDark ? "#888" : "#555", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>Cancel</button>
              <button type="submit" disabled={loading} style={{ background: "var(--btn-primary)", border: "none", borderRadius: 10, padding: "10px 24px", fontSize: 13, fontWeight: 600, color: "#fff", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", opacity: loading ? 0.7 : 1 }}>
                {loading ? "Saving…" : isEdit ? "Save changes" : "Create alert"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

// ── AI Result Display ────────────────────────────────────────────────────────
function AIResult({ result, loading, error, isDark }) {
  if (loading) return (
    <div style={{ textAlign: "center", padding: 40 }}>
      <div style={{ fontSize: 13, color: isDark ? "#666" : "#888", marginBottom: 12 }}>
        AI is thinking...
      </div>
      <Spinner />
    </div>
  );
  if (error) return (
    <div style={{ background: "rgba(245,101,101,0.1)", border: "1px solid rgba(245,101,101,0.3)", borderRadius: 10, padding: "14px 16px", fontSize: 13, color: "#f87171" }}>
      {error}
    </div>
  );
  if (!result) return null;

  // Render **bold** and bullet points from AI response
  const renderLine = (line, i) => {
    if (line.startsWith("**") && line.endsWith("**") && line.length > 4) {
      return <div key={i} style={{ fontSize: 14, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", marginTop: 16, marginBottom: 6 }}>{line.slice(2,-2)}</div>;
    }
    if (line.startsWith("• ") || line.startsWith("- ")) {
      return <div key={i} style={{ fontSize: 13, color: isDark ? "#ccc" : "#333", paddingLeft: 16, marginBottom: 4, lineHeight: 1.6 }}>{"• " + line.slice(2)}</div>;
    }
    if (line.startsWith("**Q")) {
      return <div key={i} style={{ fontSize: 13, fontWeight: 700, color: "#0071E3", marginTop: 14, marginBottom: 4 }}>{line.replace(/\*\*/g, "")}</div>;
    }
    if (line.startsWith("*Suggested")) {
      return <div key={i} style={{ fontSize: 13, color: isDark ? "#aaa" : "#555", marginBottom: 8, fontStyle: "italic", lineHeight: 1.6 }}>{line.replace(/\*/g, "")}</div>;
    }
    if (!line.trim()) return <div key={i} style={{ height: 6 }} />;
    return <div key={i} style={{ fontSize: 13, color: isDark ? "#ccc" : "#333", marginBottom: 4, lineHeight: 1.7 }}>{line}</div>;
  };

  return (
    <div style={{ background: isDark ? "#141416" : "#f8f8fb", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "20px 22px", marginTop: 16 }}>
      {result.split("\n").map((line, i) => renderLine(line, i))}
      <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
        <button
          onClick={() => navigator.clipboard.writeText(result)}
          style={{ fontSize: 11, background: "none", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 6, padding: "4px 12px", cursor: "pointer", color: isDark ? "#666" : "#555", fontFamily: "'DM Sans', sans-serif" }}
        >
          📋 Copy
        </button>
      </div>
    </div>
  );
}


// ── AI Features Page ──────────────────────────────────────────────────────────
function AIPage({ isDark = true, user, onAuthRequired, toast }) {
  const [tab, setTab] = useState("cv");
  const [result, setResult] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // CV Optimiser state
  const [cvText, setCvText] = useState("");
  const [targetRole, setTargetRole] = useState("");

  // Job Match state
  const [matchJobTitle, setMatchJobTitle] = useState("");
  const [matchJobDesc, setMatchJobDesc] = useState("");
  const [matchSkills, setMatchSkills] = useState("");

  // Application Writer state
  const [appJobTitle, setAppJobTitle] = useState("");
  const [appCompany, setAppCompany] = useState("");
  const [appJobDesc, setAppJobDesc] = useState("");
  const [appTone, setAppTone] = useState("professional");

  // Interview Prep state
  const [intJobTitle, setIntJobTitle] = useState("");
  const [intCompany, setIntCompany] = useState("");
  const [intType, setIntType] = useState("general");
  const [intJobDesc, setIntJobDesc] = useState("");

  // Job Description Writer state
  const [jdTitle, setJdTitle] = useState("");
  const [jdCompany, setJdCompany] = useState("");
  const [jdDept, setJdDept] = useState("");
  const [jdResponsibilities, setJdResponsibilities] = useState("");

  // HR Assistant state
  const [hrQuestion, setHrQuestion] = useState("");

  const inp = { width: "100%", boxSizing: "border-box", padding: "10px 14px", fontSize: 13, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 10, background: isDark ? "#141416" : "#ffffff", color: isDark ? "#f0f0f2" : "#1d1d1f", fontFamily: "'DM Sans', sans-serif", outline: "none" };
  const lbl = { fontSize: 11, fontWeight: 600, color: isDark ? "#888" : "#555", textTransform: "uppercase", letterSpacing: "0.5px", display: "block", marginBottom: 6 };

  async function runAI(endpoint, payload) {
    setLoading(true); setError(""); setResult("");
    try {
      const res = await api(endpoint, { method: "POST", body: JSON.stringify(payload) });
      setResult(res.result || "No response");
    } catch (e) {
      setError(e.message || "AI request failed. Check your API key is set.");
    } finally {
      setLoading(false);
    }
  }

  if (!user) return (
    <div style={{ textAlign: "center", padding: 60 }}>
      <div style={{ fontSize: 40, marginBottom: 16 }}>🤖</div>
      <div style={{ fontSize: 18, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 8 }}>AI Features</div>
      <div style={{ fontSize: 14, color: isDark ? "#666" : "#888", marginBottom: 24 }}>Sign in to access AI-powered career tools</div>
      <button onClick={onAuthRequired} style={{ background: "var(--btn-primary)", color: "#fff", border: "none", borderRadius: 10, padding: "10px 24px", fontSize: 14, fontWeight: 600, cursor: "pointer" }}>Sign in | Register</button>
    </div>
  );

  const tabs = [
    { id: "cv",        label: "✨ CV Review",       desc: "Get AI feedback on your CV" },
    { id: "match",     label: "🎯 Job Match",        desc: "See how well you match a job" },
    { id: "apply",     label: "✍️ Write Application", desc: "AI writes your cover letter" },
    { id: "interview", label: "🎤 Interview Prep",    desc: "Practice questions & answers" },
    { id: "jd",        label: "📝 Write Job Post",    desc: "AI writes job descriptions" },
    { id: "hr",        label: "💬 HR Assistant",      desc: "Ask any HR question" },
  ];

  const tabStyle = (t) => ({
    background: tab === t ? "#0071E3" : isDark ? "#141416" : "#ffffff",
    border: tab === t ? "none" : isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8",
    borderRadius: 10, padding: "8px 14px", fontSize: 12, fontWeight: tab === t ? 600 : 400,
    color: tab === t ? "#fff" : isDark ? "#888" : "#555",
    cursor: "pointer", fontFamily: "'DM Sans', sans-serif", whiteSpace: "nowrap",
  });

  const SubmitBtn = ({ onClick, label = "Run AI" }) => (
    <button onClick={onClick} disabled={loading} style={{ background: loading ? "#555" : "#0071E3", border: "none", borderRadius: 10, padding: "11px 24px", fontSize: 13, fontWeight: 600, color: "#fff", cursor: loading ? "default" : "pointer", fontFamily: "'DM Sans', sans-serif", marginTop: 16 }}>
      {loading ? "AI thinking…" : `✨ ${label}`}
    </button>
  );

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", letterSpacing: -0.5, marginBottom: 4 }}>AI Features</h1>
        <p style={{ fontSize: 13, color: isDark ? "#666" : "#888" }}>Powered by Claude AI — your career and hiring assistant</p>
      </div>

      {/* Tab bar */}
      <div style={{ display: "flex", gap: 8, marginBottom: 24, flexWrap: "wrap" }}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => { setTab(t.id); setResult(""); setError(""); }} style={tabStyle(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, alignItems: "start" }}>
        {/* Input panel */}
        <div style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "20px 22px" }}>

          {/* CV Optimiser */}
          {tab === "cv" && (
            <div>
              <div style={{ fontSize: 15, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 4 }}>✨ CV Optimiser</div>
              <div style={{ fontSize: 12, color: isDark ? "#666" : "#888", marginBottom: 16 }}>Paste your CV text and get specific improvement suggestions</div>
              <div style={{ marginBottom: 14 }}>
                <label style={lbl}>Paste your CV text</label>
                <textarea value={cvText} onChange={e => setCvText(e.target.value)} placeholder="Paste your full CV/resume text here..." style={{ ...inp, height: 180, resize: "vertical" }} />
              </div>
              <div style={{ marginBottom: 14 }}>
                <label style={lbl}>Target role (optional)</label>
                <input value={targetRole} onChange={e => setTargetRole(e.target.value)} placeholder="e.g. Senior Product Manager" style={inp} />
              </div>
              <SubmitBtn label="Analyse CV" onClick={() => runAI("/ai/cv/optimise", { cv_text: cvText, target_role: targetRole })} />
            </div>
          )}

          {/* Job Match */}
          {tab === "match" && (
            <div>
              <div style={{ fontSize: 15, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 4 }}>🎯 Job Match Score</div>
              <div style={{ fontSize: 12, color: isDark ? "#666" : "#888", marginBottom: 16 }}>See how well your profile matches a job</div>
              <div style={{ marginBottom: 14 }}>
                <label style={lbl}>Job title</label>
                <input value={matchJobTitle} onChange={e => setMatchJobTitle(e.target.value)} placeholder="e.g. Software Engineer" style={inp} />
              </div>
              <div style={{ marginBottom: 14 }}>
                <label style={lbl}>Job description (optional)</label>
                <textarea value={matchJobDesc} onChange={e => setMatchJobDesc(e.target.value)} placeholder="Paste the job description..." style={{ ...inp, height: 100, resize: "vertical" }} />
              </div>
              <div style={{ marginBottom: 14 }}>
                <label style={lbl}>Your skills (comma separated)</label>
                <input value={matchSkills} onChange={e => setMatchSkills(e.target.value)} placeholder="React, Python, Product Management..." style={inp} />
              </div>
              <SubmitBtn label="Score My Match" onClick={() => runAI("/ai/job/match", { job_title: matchJobTitle, job_description: matchJobDesc, candidate_skills: matchSkills.split(",").map(s => s.trim()).filter(Boolean) })} />
            </div>
          )}

          {/* Application Writer */}
          {tab === "apply" && (
            <div>
              <div style={{ fontSize: 15, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 4 }}>✍️ Application Writer</div>
              <div style={{ fontSize: 12, color: isDark ? "#666" : "#888", marginBottom: 16 }}>AI writes a tailored cover letter for you</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
                <div>
                  <label style={lbl}>Job title</label>
                  <input value={appJobTitle} onChange={e => setAppJobTitle(e.target.value)} placeholder="Software Engineer" style={inp} />
                </div>
                <div>
                  <label style={lbl}>Company</label>
                  <input value={appCompany} onChange={e => setAppCompany(e.target.value)} placeholder="MTN Nigeria" style={inp} />
                </div>
              </div>
              <div style={{ marginBottom: 14 }}>
                <label style={lbl}>Job description (optional)</label>
                <textarea value={appJobDesc} onChange={e => setAppJobDesc(e.target.value)} placeholder="Paste the job description..." style={{ ...inp, height: 80, resize: "vertical" }} />
              </div>
              <div style={{ marginBottom: 14 }}>
                <label style={lbl}>Tone</label>
                <select value={appTone} onChange={e => setAppTone(e.target.value)} style={{ ...inp, cursor: "pointer" }}>
                  <option value="professional">Professional</option>
                  <option value="friendly">Friendly</option>
                  <option value="concise">Concise</option>
                </select>
              </div>
              <SubmitBtn label="Write Cover Letter" onClick={() => {
                const profile = user?.full_name || "Candidate";
                runAI("/ai/application/write", { job_title: appJobTitle, company: appCompany, job_description: appJobDesc, candidate_name: profile, tone: appTone });
              }} />
            </div>
          )}

          {/* Interview Prep */}
          {tab === "interview" && (
            <div>
              <div style={{ fontSize: 15, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 4 }}>🎤 Interview Preparation</div>
              <div style={{ fontSize: 12, color: isDark ? "#666" : "#888", marginBottom: 16 }}>Get realistic questions and suggested answers</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
                <div>
                  <label style={lbl}>Job title</label>
                  <input value={intJobTitle} onChange={e => setIntJobTitle(e.target.value)} placeholder="Product Manager" style={inp} />
                </div>
                <div>
                  <label style={lbl}>Company (optional)</label>
                  <input value={intCompany} onChange={e => setIntCompany(e.target.value)} placeholder="MTN Nigeria" style={inp} />
                </div>
              </div>
              <div style={{ marginBottom: 14 }}>
                <label style={lbl}>Interview type</label>
                <select value={intType} onChange={e => setIntType(e.target.value)} style={{ ...inp, cursor: "pointer" }}>
                  <option value="general">General</option>
                  <option value="technical">Technical</option>
                  <option value="behavioral">Behavioral (STAR)</option>
                </select>
              </div>
              <div style={{ marginBottom: 14 }}>
                <label style={lbl}>Job description (optional)</label>
                <textarea value={intJobDesc} onChange={e => setIntJobDesc(e.target.value)} placeholder="Paste the job description for tailored questions..." style={{ ...inp, height: 80, resize: "vertical" }} />
              </div>
              <SubmitBtn label="Generate Questions" onClick={() => runAI("/ai/interview/prep", { job_title: intJobTitle, company: intCompany, interview_type: intType, job_description: intJobDesc })} />
            </div>
          )}

          {/* Job Description Writer */}
          {tab === "jd" && (
            <div>
              <div style={{ fontSize: 15, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 4 }}>📝 Job Description Writer</div>
              <div style={{ fontSize: 12, color: isDark ? "#666" : "#888", marginBottom: 16 }}>AI writes a complete job description ready to post</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
                <div>
                  <label style={lbl}>Job title</label>
                  <input value={jdTitle} onChange={e => setJdTitle(e.target.value)} placeholder="Software Engineer" style={inp} />
                </div>
                <div>
                  <label style={lbl}>Company</label>
                  <input value={jdCompany} onChange={e => setJdCompany(e.target.value)} placeholder="Your company name" style={inp} />
                </div>
              </div>
              <div style={{ marginBottom: 14 }}>
                <label style={lbl}>Department (optional)</label>
                <input value={jdDept} onChange={e => setJdDept(e.target.value)} placeholder="Engineering" style={inp} />
              </div>
              <div style={{ marginBottom: 14 }}>
                <label style={lbl}>Key responsibilities (optional)</label>
                <textarea value={jdResponsibilities} onChange={e => setJdResponsibilities(e.target.value)} placeholder="Brief notes on what this person will do..." style={{ ...inp, height: 80, resize: "vertical" }} />
              </div>
              <SubmitBtn label="Write Job Description" onClick={() => runAI("/ai/job/write-description", { job_title: jdTitle, company: jdCompany, department: jdDept, key_responsibilities: jdResponsibilities })} />
            </div>
          )}

          {/* HR Assistant */}
          {tab === "hr" && (
            <div>
              <div style={{ fontSize: 15, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 4 }}>💬 HR Assistant</div>
              <div style={{ fontSize: 12, color: isDark ? "#666" : "#888", marginBottom: 16 }}>Ask anything about HR, Nigerian labour law, or workplace issues</div>
              <div style={{ marginBottom: 14 }}>
                <label style={lbl}>Your question</label>
                <textarea value={hrQuestion} onChange={e => setHrQuestion(e.target.value)} placeholder="e.g. What is the minimum notice period for resignation in Nigeria? Can an employer reduce salary without consent?" style={{ ...inp, height: 120, resize: "vertical" }} />
              </div>
              <div style={{ background: isDark ? "#1a1a1e" : "#f8f8fb", borderRadius: 8, padding: "10px 14px", marginBottom: 14, fontSize: 12, color: isDark ? "#555" : "#aaa" }}>
                Example questions: Notice periods · Redundancy pay · Maternity leave · Employee contracts · Disciplinary procedures
              </div>
              <SubmitBtn label="Ask AI" onClick={() => runAI("/ai/hr/assistant", { question: hrQuestion })} />
            </div>
          )}
        </div>

        {/* Result panel */}
        <div>
          {!result && !loading && !error && (
            <div style={{ background: isDark ? "#141416" : "#f8f8fb", border: isDark ? "1px solid #2a2a32" : "1px solid #e8e8f0", borderRadius: 14, padding: "40px 22px", textAlign: "center" }}>
              <div style={{ fontSize: 32, marginBottom: 12 }}>✨</div>
              <div style={{ fontSize: 14, color: isDark ? "#555" : "#aaa" }}>
                {tabs.find(t => t.id === tab)?.desc}
                <br />Fill in the form and click the AI button.
              </div>
            </div>
          )}
          <AIResult result={result} loading={loading} error={error} isDark={isDark} />
        </div>
      </div>
    </div>
  );
}


// ── Billing Page ─────────────────────────────────────────────────────────────
function BillingPage({ isDark = true, user, onAuthRequired, toast }) {
  const [plans, setPlans] = useState([]);
  const [subscription, setSubscription] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [paying, setPaying] = useState(null);
  const [tab, setTab] = useState("plans");

  const planType = user?.role?.includes("candidate") || !user?.tenant_id
    ? "candidate" : "employer";

  useEffect(() => {
    if (!user) return;
    Promise.all([
      api(`/billing/plans?plan_type=${planType}`),
      api("/billing/my-subscription"),
    ]).then(([p, s]) => {
      setPlans(p);
      setSubscription(s);
    }).catch(() => {})
    .finally(() => setLoading(false));
  }, [user, planType]);

  async function loadHistory() {
    setTab("history");
    try {
      setHistory(await api("/billing/history"));
    } catch { toast("Failed to load history"); }
  }

  async function handleUpgrade(planId) {
    setPaying(planId);
    try {
      const appUrl = window.location.origin;
      const res = await api("/billing/initiate", {
        method: "POST",
        body: JSON.stringify({ plan_id: planId, callback_url: `${appUrl}/billing/success` }),
      });
      // Redirect to Paystack
      window.location.href = res.authorization_url;
    } catch (e) {
      toast(e.message || "Failed to initiate payment");
      setPaying(null);
    }
  }

  // Check for payment success callback
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const ref = params.get("reference") || params.get("trxref");
    if (ref && window.location.pathname.includes("billing/success")) {
      api(`/billing/verify/${ref}`)
        .then(r => { toast(r.message || "Payment verified!"); window.history.replaceState({}, "", "/"); })
        .catch(() => toast("Payment verification failed"));
    }
  }, []);

  if (!user) return (
    <div style={{ textAlign: "center", padding: 60 }}>
      <div style={{ fontSize: 40, marginBottom: 16 }}>💳</div>
      <div style={{ fontSize: 18, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 8 }}>Billing & Plans</div>
      <div style={{ fontSize: 14, color: isDark ? "#666" : "#888", marginBottom: 24 }}>Sign in to manage your subscription</div>
      <button onClick={onAuthRequired} style={{ background: "var(--btn-primary)", color: "#fff", border: "none", borderRadius: 10, padding: "10px 24px", fontSize: 14, fontWeight: 600, cursor: "pointer" }}>Sign in</button>
    </div>
  );

  const currentPlanId = subscription?.plan_id || `${planType}_free`;

  const planColors = {
    Free:       { badge: "rgba(136,136,136,0.15)", text: "#888" },
    Premium:    { badge: "rgba(0,113,227,0.1)",    text: "#0071E3" },
    Starter:    { badge: "rgba(61,214,140,0.1)",   text: "#3DD68C" },
    Growth:     { badge: "rgba(155,89,182,0.1)",   text: "#9B59B6" },
    Enterprise: { badge: "rgba(245,166,35,0.1)",   text: "#F5A623" },
  };

  return (
    <div style={{ maxWidth: 900 }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", letterSpacing: -0.5, marginBottom: 4 }}>Billing & Plans</h1>
        {subscription && (
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 13, color: isDark ? "#666" : "#888" }}>Current plan:</span>
            <span style={{ fontSize: 13, fontWeight: 600, color: "#0071E3" }}>{subscription.plan_name || "Free"}</span>
            {!subscription.is_free && subscription.expires_at && (
              <span style={{ fontSize: 11, color: isDark ? "#555" : "#aaa" }}>
                · renews {new Date(subscription.expires_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 8, marginBottom: 24 }}>
        {[["plans","Plans"], ["history","Billing History"]].map(([id, label]) => (
          <button key={id} onClick={() => id === "history" ? loadHistory() : setTab(id)} style={{ background: tab === id ? "#0071E3" : "none", border: tab === id ? "none" : isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 8, padding: "7px 16px", fontSize: 13, color: tab === id ? "#fff" : isDark ? "#888" : "#555", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", fontWeight: tab === id ? 600 : 400 }}>
            {label}
          </button>
        ))}
      </div>

      {/* Plans */}
      {tab === "plans" && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 16 }}>
          {loading ? <Spinner /> : plans.map(plan => {
            const isCurrentPlan = plan.id === currentPlanId;
            const colors = planColors[plan.name] || planColors.Free;
            return (
              <div key={plan.id} style={{ background: isDark ? "#141416" : "#ffffff", border: isCurrentPlan ? "2px solid #0071E3" : isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 16, padding: "22px 20px", position: "relative" }}>
                {isCurrentPlan && (
                  <div style={{ position: "absolute", top: -1, right: 16, background: "var(--btn-primary)", color: "#fff", fontSize: 10, fontWeight: 700, padding: "3px 10px", borderRadius: "0 0 8px 8px" }}>CURRENT</div>
                )}
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                  <span style={{ fontSize: 16, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f" }}>{plan.name}</span>
                  <span style={{ fontSize: 11, fontWeight: 600, background: colors.badge, color: colors.text, padding: "3px 10px", borderRadius: 20 }}>{plan.type}</span>
                </div>
                <div style={{ marginBottom: 16 }}>
                  {plan.price_ngn === 0 ? (
                    <span style={{ fontSize: 24, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f" }}>Free</span>
                  ) : (
                    <div>
                      <span style={{ fontSize: 24, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f" }}>₦{plan.price_ngn.toLocaleString()}</span>
                      <span style={{ fontSize: 12, color: isDark ? "#666" : "#888" }}>/month</span>
                    </div>
                  )}
                </div>
                <div style={{ marginBottom: 20 }}>
                  {(plan.features || []).map((f, i) => (
                    <div key={i} style={{ fontSize: 12, color: isDark ? "#aaa" : "#555", padding: "3px 0", display: "flex", gap: 6 }}>
                      <span style={{ color: "#3DD68C" }}>✓</span> {f}
                    </div>
                  ))}
                </div>
                {plan.price_ngn > 0 && !isCurrentPlan && (
                  <button
                    onClick={() => handleUpgrade(plan.id)}
                    disabled={paying === plan.id}
                    style={{ width: "100%", background: "var(--btn-primary)", border: "none", borderRadius: 10, padding: "10px", fontSize: 13, fontWeight: 600, color: "#fff", cursor: paying ? "default" : "pointer", fontFamily: "'DM Sans', sans-serif", opacity: paying === plan.id ? 0.7 : 1 }}
                  >
                    {paying === plan.id ? "Redirecting…" : plan.name === "Enterprise" ? "Contact Sales" : `Upgrade — ₦${plan.price_ngn.toLocaleString()}/mo`}
                  </button>
                )}
                {isCurrentPlan && plan.price_ngn > 0 && (
                  <div style={{ fontSize: 12, color: "#3DD68C", textAlign: "center", marginTop: 4 }}>✓ Active subscription</div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* History */}
      {tab === "history" && (
        <div>
          {history.length === 0 ? (
            <div style={{ textAlign: "center", padding: 40, color: isDark ? "#555" : "#aaa", fontSize: 13 }}>No billing history yet</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {history.map(t => (
                <div key={t.id} style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 12, padding: "14px 18px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 500, color: isDark ? "#f0f0f2" : "#1d1d1f", textTransform: "capitalize" }}>{(t.plan_id || "").replace(/_/g, " ")}</div>
                    <div style={{ fontSize: 11, color: isDark ? "#555" : "#aaa" }}>{new Date(t.created_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })} · {t.reference}</div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div style={{ fontSize: 14, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f" }}>₦{(t.amount || 0).toLocaleString()}</div>
                    <span style={{ fontSize: 11, color: t.status === "success" ? "#3DD68C" : "#f87171", fontWeight: 600, textTransform: "capitalize" }}>{t.status}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div style={{ marginTop: 32, padding: "16px 20px", background: isDark ? "#141416" : "#f8f8fb", borderRadius: 12, border: isDark ? "1px solid #2a2a32" : "1px solid #e8e8f0" }}>
        <div style={{ fontSize: 12, color: isDark ? "#555" : "#aaa", lineHeight: 1.6 }}>
          Payments processed securely by <strong style={{ color: isDark ? "#888" : "#666" }}>Paystack</strong> · All prices in Nigerian Naira (NGN) · Cancel anytime
        </div>
      </div>
    </div>
  );
}


// ── Mini Bar Chart ───────────────────────────────────────────────────────────
function MiniBarChart({ data, labelKey, valueKey, color = "#0071E3", isDark, height = 120 }) {
  if (!data || data.length === 0) return (
    <div style={{ height, display: "flex", alignItems: "center", justifyContent: "center", color: isDark ? "#444" : "#ccc", fontSize: 12 }}>No data</div>
  );
  const max = Math.max(...data.map(d => d[valueKey] || 0), 1);
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height, paddingTop: 8 }}>
      {data.map((d, i) => {
        const pct = ((d[valueKey] || 0) / max) * 100;
        return (
          <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 3 }}>
            <div style={{ fontSize: 9, color: isDark ? "#555" : "#aaa" }}>{d[valueKey] || 0}</div>
            <div style={{ width: "100%", height: `${Math.max(pct, 3)}%`, background: color, borderRadius: "3px 3px 0 0", transition: "height 0.3s ease", minHeight: 3 }} />
            <div style={{ fontSize: 8, color: isDark ? "#444" : "#bbb", transform: "rotate(-45deg)", transformOrigin: "center", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 28 }}>
              {String(d[labelKey] || "").slice(-5)}
            </div>
          </div>
        );
      })}
    </div>
  );
}


// ── Donut Chart ───────────────────────────────────────────────────────────────
function DonutChart({ data, labelKey, valueKey, isDark, size = 140 }) {
  if (!data || data.length === 0) return null;
  const total = data.reduce((s, d) => s + (d[valueKey] || 0), 0);
  if (total === 0) return null;

  const COLORS = ["#0071E3", "#3DD68C", "#F5A623", "#9B59B6", "#f87171", "#38bdf8", "#fb923c"];
  let cumulative = 0;
  const slices = data.map((d, i) => {
    const pct = (d[valueKey] || 0) / total;
    const start = cumulative;
    cumulative += pct;
    return { ...d, pct, start, color: COLORS[i % COLORS.length] };
  });

  const r = 50; const cx = 70; const cy = 70;
  const polarToCartesian = (pct) => {
    const angle = pct * 2 * Math.PI - Math.PI / 2;
    return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
  };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
      <svg width={size} height={size} viewBox="0 0 140 140">
        {slices.map((s, i) => {
          if (s.pct === 0) return null;
          const start = polarToCartesian(s.start);
          const end = polarToCartesian(s.start + s.pct);
          const largeArc = s.pct > 0.5 ? 1 : 0;
          const d = `M ${cx} ${cy} L ${start.x} ${start.y} A ${r} ${r} 0 ${largeArc} 1 ${end.x} ${end.y} Z`;
          return <path key={i} d={d} fill={s.color} opacity={0.9} />;
        })}
        <circle cx={cx} cy={cy} r={30} fill={isDark ? "#141416" : "#ffffff"} />
        <text x={cx} y={cy+4} textAnchor="middle" fontSize="11" fill={isDark ? "#888" : "#666"}>{total}</text>
      </svg>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {slices.map((s, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 8, height: 8, borderRadius: 2, background: s.color, flexShrink: 0 }} />
            <span style={{ fontSize: 11, color: isDark ? "#888" : "#555", textTransform: "capitalize" }}>
              {s[labelKey]}: {s[valueKey]}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}


// ── Analytics Page ────────────────────────────────────────────────────────────
function AnalyticsPage({ isDark = true, user, onAuthRequired, toast }) {
  const [tab, setTab] = useState("candidate");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const isAdmin = user && ["super_admin", "platform_admin"].includes(user.role);
  const isEmployer = user && (user.tenant_id || ["org_owner","hr_admin","recruiter"].includes(user.role));

  const tabs = [
    { id: "candidate", label: "📊 My Stats",   show: !!user },
    { id: "employer",  label: "🏢 Hiring",      show: isEmployer },
    { id: "platform",  label: "🌍 Platform",    show: isAdmin },
  ].filter(t => t.show);

  async function loadData(t) {
    setTab(t); setLoading(true); setData(null);
    try {
      const endpoints = {
        candidate: "/analytics/candidate/overview",
        employer:  "/analytics/employer/overview?days=30",
        platform:  "/analytics/platform/overview?days=30",
      };
      setData(await api(endpoints[t]));
    } catch (e) {
      toast(e.message || "Failed to load analytics");
    } finally { setLoading(false); }
  }

  useEffect(() => {
    if (user && tabs.length > 0) loadData(tabs[0].id);
  }, [user]);

  async function exportCSV(type) {
    try {
      const res = await fetch(`${API}/analytics/export/${type}`, {
        headers: { Authorization: `Bearer ${localStorage.getItem("js_access_token")}` }
      });
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${type}_${new Date().toISOString().slice(0,10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch { toast("Export failed"); }
  }

  if (!user) return (
    <div style={{ textAlign: "center", padding: 60 }}>
      <div style={{ fontSize: 40, marginBottom: 16 }}>📊</div>
      <div style={{ fontSize: 18, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 8 }}>Analytics</div>
      <div style={{ fontSize: 14, color: isDark ? "#666" : "#888", marginBottom: 24 }}>Sign in to view your analytics</div>
      <button onClick={onAuthRequired} style={{ background: "var(--btn-primary)", color: "#fff", border: "none", borderRadius: 10, padding: "10px 24px", fontSize: 14, fontWeight: 600, cursor: "pointer" }}>Sign in</button>
    </div>
  );

  const tabStyle = (t) => ({
    background: tab === t ? "#0071E3" : "none",
    border: tab === t ? "none" : isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8",
    borderRadius: 8, padding: "7px 16px", fontSize: 13,
    color: tab === t ? "#fff" : isDark ? "#888" : "#555",
    cursor: "pointer", fontFamily: "'DM Sans', sans-serif",
    fontWeight: tab === t ? 600 : 400,
  });

  const Card = ({ label, value, sub, color = "#0071E3" }) => (
    <div style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "18px 20px", flex: 1, minWidth: 120 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: isDark ? "#666" : "#999", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 8 }}>{label}</div>
      <div style={{ fontSize: 28, fontWeight: 700, color, letterSpacing: -1, marginBottom: 2 }}>{value ?? "—"}</div>
      {sub && <div style={{ fontSize: 11, color: isDark ? "#555" : "#aaa" }}>{sub}</div>}
    </div>
  );

  const Section = ({ title, children }) => (
    <div style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "20px 22px", marginBottom: 16 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 16 }}>{title}</div>
      {children}
    </div>
  );

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24, flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", letterSpacing: -0.5, marginBottom: 4 }}>Analytics</h1>
          <p style={{ fontSize: 13, color: isDark ? "#666" : "#888" }}>Performance insights and reports</p>
        </div>
        {(isEmployer || isAdmin) && (
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={() => exportCSV("applications")} style={{ fontSize: 12, background: "none", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 8, padding: "7px 14px", cursor: "pointer", color: isDark ? "#888" : "#555", fontFamily: "'DM Sans', sans-serif" }}>
              ↓ Export Applications
            </button>
            {isAdmin && (
              <button onClick={() => exportCSV("jobs")} style={{ fontSize: 12, background: "none", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 8, padding: "7px 14px", cursor: "pointer", color: isDark ? "#888" : "#555", fontFamily: "'DM Sans', sans-serif" }}>
                ↓ Export Jobs
              </button>
            )}
          </div>
        )}
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 24 }}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => loadData(t.id)} style={tabStyle(t.id)}>{t.label}</button>
        ))}
      </div>

      {loading && <Spinner />}

      {/* Candidate analytics */}
      {tab === "candidate" && data && !loading && (
        <div>
          <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
            <Card label="Total Applied"    value={data.summary?.total_applications} color="#0071E3" />
            <Card label="Shortlisted"      value={data.summary?.shortlisted}        color="#F5A623" />
            <Card label="Hired"            value={data.summary?.hired}              color="#3DD68C" />
            <Card label="Response Rate"    value={`${data.summary?.response_rate_pct}%`} color="#9B59B6" />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <Section title="Applications by Status">
              <DonutChart data={data.by_status} labelKey="status" valueKey="count" isDark={isDark} />
            </Section>
            <Section title="Monthly Applications">
              <MiniBarChart data={data.monthly_trend} labelKey="month" valueKey="count" isDark={isDark} color="#0071E3" />
            </Section>
          </div>
          <Section title="Recent Applications">
            {(data.recent_applications || []).map(a => (
              <div key={a.id} style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: isDark ? "1px solid #1e1e24" : "1px solid #f0f0f4" }}>
                <div>
                  <div style={{ fontSize: 13, color: isDark ? "#e0e0e0" : "#1d1d1f" }}>{a.job_title || "Unknown job"}</div>
                  <div style={{ fontSize: 11, color: isDark ? "#555" : "#aaa" }}>{a.company} · {new Date(a.submitted_at).toLocaleDateString("en-GB")}</div>
                </div>
                <span style={{ fontSize: 11, fontWeight: 600, textTransform: "capitalize", color: a.status === "hired" ? "#3DD68C" : a.status === "rejected" ? "#f87171" : "#F5A623" }}>{a.status}</span>
              </div>
            ))}
          </Section>
        </div>
      )}

      {/* Employer analytics */}
      {tab === "employer" && data && !loading && (
        <div>
          <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
            <Card label="Active Jobs"      value={data.summary?.active_jobs}        color="#0071E3" />
            <Card label="Total Applicants" value={data.summary?.total_applications} color="#F5A623" sub={`+${data.summary?.new_applications} this period`} />
            <Card label="Hired"            value={data.summary?.hired}              color="#3DD68C" />
            <Card label="Hire Rate"        value={`${data.summary?.hire_rate_pct}%`} color="#9B59B6" />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
            <Section title="Application Pipeline">
              <DonutChart data={data.pipeline} labelKey="status" valueKey="count" isDark={isDark} />
            </Section>
            <Section title="Daily Applications (30 days)">
              <MiniBarChart data={data.daily_trend} labelKey="date" valueKey="count" isDark={isDark} color="#3DD68C" />
            </Section>
          </div>
          <Section title="Top Jobs by Applications">
            {(data.top_jobs || []).map(j => (
              <div key={j.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 0", borderBottom: isDark ? "1px solid #1e1e24" : "1px solid #f0f0f4" }}>
                <div style={{ fontSize: 13, color: isDark ? "#e0e0e0" : "#1d1d1f" }}>{j.title}</div>
                <div style={{ display: "flex", gap: 16, fontSize: 12 }}>
                  <span style={{ color: "#0071E3" }}>{j.app_count} apps</span>
                  <span style={{ color: "#3DD68C" }}>{j.hired_count} hired</span>
                </div>
              </div>
            ))}
          </Section>
        </div>
      )}

      {/* Platform analytics */}
      {tab === "platform" && data && !loading && (
        <div>
          <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
            <Card label="Total Users"   value={data.totals?.users}         sub={`+${data.growth?.new_users} new`}  color="#0071E3" />
            <Card label="Active Jobs"   value={data.totals?.jobs}          sub={`+${data.growth?.new_jobs} new`}   color="#F5A623" />
            <Card label="Applications"  value={data.totals?.applications}  sub={`+${data.growth?.new_applications} new`} color="#3DD68C" />
            <Card label="Revenue (NGN)" value={`₦${(data.totals?.revenue_ngn||0).toLocaleString()}`} color="#9B59B6" />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
            <Section title="Daily Signups (30 days)">
              <MiniBarChart data={data.charts?.daily_signups} labelKey="date" valueKey="count" isDark={isDark} color="#0071E3" />
            </Section>
            <Section title="Daily Applications (30 days)">
              <MiniBarChart data={data.charts?.daily_applications} labelKey="date" valueKey="count" isDark={isDark} color="#3DD68C" />
            </Section>
            <Section title="Jobs by Type">
              <DonutChart data={data.charts?.jobs_by_type} labelKey="job_type" valueKey="count" isDark={isDark} />
            </Section>
            <Section title="Jobs by Source">
              <DonutChart data={data.charts?.jobs_by_source} labelKey="source" valueKey="count" isDark={isDark} />
            </Section>
          </div>
          <Section title="Top Hiring Companies">
            {(data.top_companies || []).map((c, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "7px 0", borderBottom: isDark ? "1px solid #1e1e24" : "1px solid #f0f0f4" }}>
                <div style={{ fontSize: 13, color: isDark ? "#e0e0e0" : "#1d1d1f" }}>{c.company}</div>
                <span style={{ fontSize: 12, fontWeight: 600, color: "#0071E3" }}>{c.job_count} jobs</span>
              </div>
            ))}
          </Section>
        </div>
      )}
    </div>
  );
}


// ── Docs / Legal Page ────────────────────────────────────────────────────────
function DocsPage({ isDark = true, section = "privacy" }) {
  const [activeSection, setActiveSection] = useState(section);

  const sections = [
    { id: "privacy",   label: "Privacy Policy" },
    { id: "terms",     label: "Terms of Service" },
    { id: "api",       label: "API Reference" },
    { id: "employers", label: "Employer Guide" },
  ];

  const prose = (text) => ({
    fontSize: 13, color: isDark ? "#ccc" : "#444",
    lineHeight: 1.8, marginBottom: 12,
  });

  const h2 = { fontSize: 18, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 8, marginTop: 28, letterSpacing: -0.3 };
  const h3 = { fontSize: 14, fontWeight: 600, color: isDark ? "#e0e0e0" : "#1d1d1f", marginBottom: 6, marginTop: 18 };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: 32, maxWidth: 900 }}>
      {/* Sidebar */}
      <div>
        <div style={{ fontSize: 11, fontWeight: 600, color: isDark ? "#666" : "#aaa", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 12 }}>Documentation</div>
        {sections.map(s => (
          <button key={s.id} onClick={() => setActiveSection(s.id)} style={{ display: "block", width: "100%", textAlign: "left", background: activeSection === s.id ? "rgba(0,113,227,0.1)" : "none", border: "none", borderRadius: 8, padding: "8px 12px", fontSize: 13, color: activeSection === s.id ? "#0071E3" : isDark ? "#888" : "#555", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", fontWeight: activeSection === s.id ? 600 : 400, marginBottom: 2 }}>
            {s.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={{ maxWidth: 680 }}>

        {/* Privacy Policy */}
        {activeSection === "privacy" && (
          <div>
            <h1 style={{ fontSize: 26, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 4 }}>Privacy Policy</h1>
            <p style={{ ...prose(true), color: isDark ? "#555" : "#aaa", marginBottom: 28 }}>Last updated: June 2026</p>
            {[
              ["1. Information We Collect", "We collect your name, email and password (hashed, never stored in plain text) when you register. Profile information you provide such as phone, location, skills and CV links. Application data when you apply for jobs. Usage data to improve the service. Payment transaction references (processed securely by Paystack — we never store card details). IP address and device information for security."],
              ["2. How We Use Your Information", "To operate the JobStream platform. To match candidates with relevant jobs. To send transactional emails (password resets, confirmations, job alerts). To process payments. To provide AI features when requested. To detect fraud and maintain security. To comply with Nigerian law."],
              ["3. Information Sharing", "We do not sell your personal data. When you apply for a job, your application details are shared with the employer. We use Resend (email), Paystack (payments), Railway (hosting) and Anthropic (AI). We may disclose data if required by law or court order."],
              ["4. Your Rights (NDPR)", "Under Nigeria's Data Protection Regulation, you have the right to access, correct, delete or export your data. Contact privacy@jobstream.ng to exercise these rights."],
              ["5. Data Security", "Passwords are hashed with bcrypt. All data is encrypted in transit (HTTPS). Access tokens expire after 30 minutes. Rate limiting and account lockout protect against brute force. All actions are audit logged."],
              ["6. Data Retention", "Account data is retained while active. Application data for 2 years. Audit logs for 1 year. Deleted accounts have personal data removed within 30 days."],
              ["7. Contact", "Email: privacy@jobstream.ng"],
            ].map(([title, body]) => (
              <div key={title}>
                <h2 style={h2}>{title}</h2>
                <p style={prose(true)}>{body}</p>
              </div>
            ))}
          </div>
        )}

        {/* Terms of Service */}
        {activeSection === "terms" && (
          <div>
            <h1 style={{ fontSize: 26, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 4 }}>Terms of Service</h1>
            <p style={{ ...prose(true), color: isDark ? "#555" : "#aaa", marginBottom: 28 }}>Last updated: June 2026</p>
            {[
              ["1. Acceptance", "By registering or using JobStream, you agree to these Terms and our Privacy Policy. You must be at least 18 and legally able to enter contracts under Nigerian law."],
              ["2. Accounts", "You are responsible for your account security. Provide accurate information. Do not share your account. We may suspend accounts that violate these terms."],
              ["3. Candidate Rules", "Provide truthful information on your profile and applications. Do not use automated tools for bulk applications. Do not impersonate others."],
              ["4. Employer Rules", "Post only genuine, legal job opportunities. Do not discriminate based on protected characteristics. Do not harvest candidate data for spam."],
              ["5. Prohibited Uses", "You may not post fraudulent listings, hack or disrupt the platform, upload malware, or violate Nigerian or international law."],
              ["6. AI Features", "AI-generated content is for informational purposes only. Review all AI output before use. We do not guarantee accuracy."],
              ["7. Payments", "Billed monthly in NGN via Paystack. Subscriptions auto-renew until cancelled. Refunds available within 7 days for unused subscriptions."],
              ["8. Governing Law", "Governed by Nigerian law. Disputes resolved in Nigerian courts. Contact: legal@jobstream.ng"],
            ].map(([title, body]) => (
              <div key={title}>
                <h2 style={h2}>{title}</h2>
                <p style={prose(true)}>{body}</p>
              </div>
            ))}
          </div>
        )}

        {/* API Reference */}
        {activeSection === "api" && (
          <div>
            <h1 style={{ fontSize: 26, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 4 }}>API Reference</h1>
            <p style={{ ...prose(true), marginBottom: 28 }}>
              The JobStream API is a REST API. Interactive documentation is available at{" "}
              <a href="/docs" target="_blank" style={{ color: "#0071E3" }}>/docs</a> (Swagger UI).
            </p>

            {[
              { title: "Authentication", items: [
                ["POST /auth/register", "Register a new user. Returns access + refresh tokens."],
                ["POST /auth/login", "Login with email + password."],
                ["POST /auth/refresh", "Refresh access token using refresh token."],
                ["POST /auth/logout", "Invalidate session."],
                ["POST /auth/forgot-password", "Request password reset email."],
                ["GET /auth/me", "Get current user profile."],
              ]},
              { title: "Jobs", items: [
                ["GET /jobs", "List jobs. Params: search, job_type, department, company, limit, offset."],
                ["POST /jobs", "Post a manual job (employer, auth required)."],
                ["GET /jobs/{id}", "Get single job by ID."],
                ["POST /jobs/{id}/apply", "Apply for a job (auth required)."],
                ["GET /jobs/saved", "Get saved jobs (auth required)."],
                ["POST /jobs/{id}/save", "Save a job (auth required)."],
              ]},
              { title: "Organizations", items: [
                ["GET /organizations", "List companies. Params: search, industry."],
                ["GET /organizations/{id}", "Get company by ID."],
                ["GET /organizations/{id}/jobs", "Get jobs at a company."],
                ["GET /sitemap.xml", "SEO sitemap of all jobs and companies."],
              ]},
              { title: "AI Features", items: [
                ["POST /ai/cv/optimise", "AI CV review. Body: {cv_text, target_role}."],
                ["POST /ai/job/match", "Score job match. Body: {job_title, candidate_skills}."],
                ["POST /ai/application/write", "Write cover letter. Body: {job_title, company, tone}."],
                ["POST /ai/interview/prep", "Interview questions. Body: {job_title, interview_type}."],
                ["POST /ai/job/write-description", "Write job description. Body: {job_title, company}."],
                ["POST /ai/hr/assistant", "HR question answering. Body: {question}."],
              ]},
              { title: "Billing", items: [
                ["GET /billing/plans", "List all plans with pricing."],
                ["GET /billing/my-subscription", "Current user subscription."],
                ["POST /billing/initiate", "Start Paystack payment. Body: {plan_id}."],
                ["POST /billing/webhook", "Paystack webhook endpoint."],
              ]},
            ].map(({ title, items }) => (
              <div key={title} style={{ marginBottom: 24 }}>
                <h2 style={h2}>{title}</h2>
                {items.map(([endpoint, desc]) => (
                  <div key={endpoint} style={{ marginBottom: 10, padding: "10px 14px", background: isDark ? "#1a1a1e" : "#f8f8fb", borderRadius: 8, border: isDark ? "1px solid #2a2a32" : "1px solid #e8e8f0" }}>
                    <code style={{ fontSize: 12, color: "#0071E3", fontFamily: "'DM Mono', monospace" }}>{endpoint}</code>
                    <div style={{ fontSize: 12, color: isDark ? "#888" : "#666", marginTop: 4 }}>{desc}</div>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}

        {/* Employer Guide */}
        {activeSection === "employers" && (
          <div>
            <h1 style={{ fontSize: 26, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 4 }}>Employer Guide</h1>
            <p style={{ ...prose(true), marginBottom: 28 }}>How to use JobStream to hire the best talent in Nigeria and Africa.</p>

            {[
              ["Getting Started", "Register an account and go to the Employer section in the sidebar. Click 'Create workspace' to set up your organisation workspace. Enter your company name and choose a unique workspace URL (e.g. jobstream.ng/acme-corp)."],
              ["Posting Jobs", "From the Employer dashboard, click '+ Post a job'. Fill in the job title, company, location, type, description, and how candidates should apply (external URL or email). Jobs appear on the job board immediately. You can also use the AI Job Description Writer under AI Tools to generate a complete description from basic notes."],
              ["Managing Applications", "Click any job in your Employer dashboard to see all applications. Each applicant shows their name, email, cover note and CV link. Use the status dropdown to move candidates through the pipeline: New → Reviewing → Shortlisted → Interview → Offer → Hired."],
              ["Workspace Dashboard", "Go to Workspace in the sidebar for your hiring analytics. See active jobs, total applicants, hired count, offer rate and a full Kanban pipeline view of all candidates across all stages."],
              ["Team Management", "Invite team members from the Workspace → Team tab. Assign roles: HR Admin, Recruiter, Hiring Manager or Interviewer. Each role has appropriate permissions — interviewers can submit feedback but can't post jobs."],
              ["Plans & Billing", "The Free plan allows up to 3 active jobs. Upgrade to Starter (₦15,000/mo, 10 jobs) or Growth (₦35,000/mo, 50 jobs) from the Billing page. Payments are processed securely by Paystack."],
              ["Need help?", "Contact us at support@jobstream.ng"],
            ].map(([title, body]) => (
              <div key={title}>
                <h2 style={h2}>{title}</h2>
                <p style={prose(true)}>{body}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}


// ── Privacy Policy Page ──────────────────────────────────────────────────────
function PrivacyPage({ isDark = true }) {
  const s = { fontSize: 13, color: isDark ? "#aaa" : "#555", lineHeight: 1.8, marginBottom: 12 };
  const h = { fontSize: 16, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 8, marginTop: 24 };

  return (
    <div style={{ maxWidth: 720 }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 4 }}>Privacy Policy</h1>
      <p style={{ fontSize: 12, color: isDark ? "#555" : "#aaa", marginBottom: 32 }}>Last updated: June 2026</p>

      <p style={s}>JobStream ("we", "us", "our") is committed to protecting your personal information in compliance with the Nigeria Data Protection Regulation (NDPR) 2019 and applicable data protection laws.</p>

      <h2 style={h}>1. Information We Collect</h2>
      <p style={s}>We collect information you provide directly: name, email address, phone number, CV/resume, work history, skills, and application details. We also collect usage data such as pages visited and features used.</p>

      <h2 style={h}>2. How We Use Your Information</h2>
      <p style={s}>We use your information to: match you with relevant job opportunities, allow employers to review your applications, send job alerts you have subscribed to, improve our platform, and comply with legal obligations.</p>

      <h2 style={h}>3. Data Sharing</h2>
      <p style={s}>We share your application information with employers you apply to. We do not sell your personal data to third parties. We may share data with service providers (email, payments, cloud hosting) who process data on our behalf under data processing agreements.</p>

      <h2 style={h}>4. Data Retention</h2>
      <p style={s}>We retain your account data for as long as your account is active. Application data is retained for 24 months. You may request deletion of your data at any time by contacting support@jobstream.ng.</p>

      <h2 style={h}>5. Your Rights (NDPR)</h2>
      <p style={s}>Under the NDPR you have the right to: access your personal data, correct inaccurate data, request deletion of your data, withdraw consent, and lodge a complaint with the National Information Technology Development Agency (NITDA).</p>

      <h2 style={h}>6. Security</h2>
      <p style={s}>We implement industry-standard security measures including encryption in transit (HTTPS), hashed passwords, JWT-based authentication, rate limiting, and regular security audits.</p>

      <h2 style={h}>7. Contact</h2>
      <p style={s}>For privacy enquiries: privacy@jobstream.ng</p>
    </div>
  );
}


// ── Terms of Service Page ─────────────────────────────────────────────────────
function TermsPage({ isDark = true }) {
  const s = { fontSize: 13, color: isDark ? "#aaa" : "#555", lineHeight: 1.8, marginBottom: 12 };
  const h = { fontSize: 16, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 8, marginTop: 24 };

  return (
    <div style={{ maxWidth: 720 }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 4 }}>Terms of Service</h1>
      <p style={{ fontSize: 12, color: isDark ? "#555" : "#aaa", marginBottom: 32 }}>Last updated: June 2026</p>

      <p style={s}>By using JobStream you agree to these terms. Please read them carefully.</p>

      <h2 style={h}>1. Use of Service</h2>
      <p style={s}>JobStream provides a job board and recruitment platform. You must be at least 18 years old to use our service. You are responsible for maintaining the confidentiality of your account credentials.</p>

      <h2 style={h}>2. Candidate Responsibilities</h2>
      <p style={s}>You warrant that all information in your profile and applications is accurate and truthful. Fraudulent applications may result in account termination and may be reported to relevant authorities.</p>

      <h2 style={h}>3. Employer Responsibilities</h2>
      <p style={s}>Employers must post only genuine job opportunities. Job listings must comply with Nigerian labour law and must not discriminate based on protected characteristics. We reserve the right to remove any listing that violates these terms.</p>

      <h2 style={h}>4. Intellectual Property</h2>
      <p style={s}>JobStream and its content are owned by Seunweb. You may not reproduce, distribute or create derivative works without our written permission.</p>

      <h2 style={h}>5. Payments and Refunds</h2>
      <p style={s}>Subscription fees are charged monthly via Paystack. Subscriptions auto-renew unless cancelled. Refunds are provided at our discretion for technical failures. No refunds for change of mind after the billing cycle has started.</p>

      <h2 style={h}>6. Limitation of Liability</h2>
      <p style={s}>JobStream is a platform connecting candidates and employers. We are not liable for hiring decisions, employment outcomes, or disputes between candidates and employers.</p>

      <h2 style={h}>7. Governing Law</h2>
      <p style={s}>These terms are governed by the laws of the Federal Republic of Nigeria. Disputes shall be resolved in Nigerian courts.</p>

      <h2 style={h}>8. Contact</h2>
      <p style={s}>Legal enquiries: legal@jobstream.ng</p>
    </div>
  );
}


// ── My Alerts Page ───────────────────────────────────────────────────────────
function MyAlertsPage({ isDark = true, user, onAuthRequired, toast }) {
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const [showCreate, setShowCreate] = useState(false);

  function load() {
    setLoading(true);
    api("/job-alerts/my").then(setAlerts).catch(() => {}).finally(() => setLoading(false));
  }

  useEffect(() => { if (user) load(); }, [user]);

  async function toggleActive(alert) {
    try {
      await api(`/job-alerts/${alert.id}`, { method: "PATCH", body: JSON.stringify({ is_active: !alert.is_active }) });
      setAlerts(prev => prev.map(a => a.id === alert.id ? { ...a, is_active: !a.is_active } : a));
    } catch { toast("Failed to update alert"); }
  }

  async function removeAlert(alert) {
    try {
      await api(`/job-alerts/mine/${alert.id}`, { method: "DELETE" });
      setAlerts(prev => prev.filter(a => a.id !== alert.id));
      toast("Alert deleted");
    } catch { toast("Failed to delete alert"); }
  }

  if (!user) return (
    <div style={{ textAlign: "center", padding: 60 }}>
      <div style={{ fontSize: 40, marginBottom: 16 }}>🔔</div>
      <div style={{ fontSize: 18, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 8 }}>Your job alerts</div>
      <div style={{ fontSize: 14, color: isDark ? "#666" : "#888", marginBottom: 24 }}>Sign in to manage your job alerts</div>
      <button onClick={onAuthRequired} style={{ background: "var(--btn-primary)", color: "#fff", border: "none", borderRadius: 10, padding: "10px 24px", fontSize: 14, fontWeight: 600, cursor: "pointer" }}>Sign in | Register</button>
    </div>
  );

  return (
    <div style={{ maxWidth: 720 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24, flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", letterSpacing: -0.5, marginBottom: 4 }}>My Alerts</h1>
          <p style={{ fontSize: 13, color: isDark ? "#666" : "#888" }}>{alerts.length} alert{alerts.length !== 1 ? "s" : ""} configured</p>
        </div>
        <button onClick={() => setShowCreate(true)} style={{ background: "var(--btn-primary)", border: "none", borderRadius: 10, padding: "10px 20px", fontSize: 13, fontWeight: 600, color: "#fff", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>
          + New alert
        </button>
      </div>

      {loading && <Spinner />}

      {!loading && alerts.length === 0 && (
        <div style={{ textAlign: "center", padding: 60 }}>
          <div style={{ fontSize: 40, marginBottom: 16 }}>🔔</div>
          <div style={{ fontSize: 16, fontWeight: 500, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 8 }}>No alerts yet</div>
          <div style={{ fontSize: 13, color: isDark ? "#666" : "#888" }}>Create an alert to get notified about new matching jobs by email</div>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {alerts.map(alert => (
          <div key={alert.id} style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "16px 20px", opacity: alert.is_active ? 1 : 0.55 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 6 }}>{alert.keywords}</div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  <Chip isDark={isDark}>📍 {alert.location || "Any location"}</Chip>
                  {alert.industry && <Chip variant="accent" isDark={isDark}>{alert.industry}</Chip>}
                  <Chip isDark={isDark}>{alert.frequency === "daily" ? "Daily" : "Weekly"} · {alert.send_time}</Chip>
                  {!alert.is_active && <Chip variant="red" isDark={isDark}>Paused</Chip>}
                </div>
              </div>
              <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                <button onClick={() => setEditing(alert)} title="Edit" style={{ background: "none", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 8, padding: "6px 10px", fontSize: 12, color: isDark ? "#888" : "#555", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>✏️</button>
                <button onClick={() => toggleActive(alert)} title={alert.is_active ? "Pause" : "Resume"} style={{ background: "none", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 8, padding: "6px 10px", fontSize: 12, color: isDark ? "#888" : "#555", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>{alert.is_active ? "⏸" : "▶"}</button>
                <button onClick={() => removeAlert(alert)} title="Delete" style={{ background: "none", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 8, padding: "6px 10px", fontSize: 12, color: "#f87171", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>✕</button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {showCreate && (
        <JobAlertsModal isDark={isDark} user={user} toast={toast} onClose={(saved) => { setShowCreate(false); if (saved) load(); }} />
      )}
      {editing && (
        <JobAlertsModal isDark={isDark} user={user} toast={toast} existingAlert={editing} onClose={(saved) => { setEditing(null); if (saved) load(); }} />
      )}
    </div>
  );
}


function ScraperPage({ toast, isDark = true }) {
  const [companies, setCompanies] = useState([]);
  const [history, setHistory] = useState([]);
  const [newName, setNewName] = useState("");
  const [newIndustry, setNewIndustry] = useState("");
  const [newUrl, setNewUrl] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState(null); // company id currently being scraped
  const [industryOptions, setIndustryOptions] = useState([]);
  const [companySearch, setCompanySearch] = useState("");
  const [companyIndustryFilter, setCompanyIndustryFilter] = useState("");

  async function load() {
    try {
      const [c, h] = await Promise.all([
        api("/companies").catch(() => []),
        api("/scrape/history").catch(() => []),
      ]);
      setCompanies(Array.isArray(c) ? c : []);
      setHistory(Array.isArray(h) ? h : []);
    } catch (e) {
      console.error("ScraperPage load error:", e);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    api("/job-alerts/meta").then(m => setIndustryOptions(m.industries || [])).catch(() => {});
  }, []);

  async function addCompany() {
    if (!newName || !newUrl) return;
    try {
      await api("/companies", { method: "POST", body: JSON.stringify({ name: newName, url: newUrl, industry: newIndustry }) });
      setNewName(""); setNewUrl(""); setNewIndustry("");
      load();
      toast(`Added ${newName}`);
    } catch (e) { toast("Failed: " + e.message); }
  }

  async function updateIndustry(id, industry) {
    try {
      await api(`/companies/${id}`, { method: "PATCH", body: JSON.stringify({ industry }) });
      setCompanies(prev => prev.map(c => c.id === id ? { ...c, industry } : c));
      toast("Industry updated — re-scrape to apply to existing jobs");
    } catch (e) { toast("Failed: " + e.message); }
  }

  async function removeCompany(id, name) {
    await api(`/companies/${id}`, { method: "DELETE" });
    load();
    toast(`Removed ${name}`);
  }

  async function registerAsOrg(company) {
    try {
      // Derive a slug from company name
      const slug = company.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
      await api("/organizations", {
        method: "POST",
        body: JSON.stringify({
          name: company.name,
          legal_name: company.name,
          website: company.url,
          industry: company.industry || "",
          slug,
          description: "",
          country: "Nigeria",
          size: "",
          logo_url: "",
          rc_number: "",
          tin: "",
          previous_names: [],
        }),
      });
      toast(`${company.name} registered as an organization — company page now available`);
    } catch (e) {
      toast(e.message?.includes("already") ? `${company.name} is already an organization` : `Failed: ${e.message}`);
    }
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

  async function exportCompanies() {
    try {
      const res = await api("/companies/export");
      const blob = new Blob([JSON.stringify(res, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "jobstream-companies.json";
      a.click();
      toast(`Exported ${res.count} companies`);
    } catch (e) { toast(e.message || "Export failed"); }
  }

  async function importCompanies() {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json";
    input.onchange = async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      try {
        const text = await file.text();
        const data = JSON.parse(text);
        const res = await api("/companies/import", { method: "POST", body: JSON.stringify(data) });
        toast(res.message);
        load();
      } catch (err) { toast(err.message || "Import failed"); }
    };
    input.click();
  }

  const inp = {
    background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 8,
    padding: "9px 12px", fontSize: 13, color: isDark ? "#f0f0f2" : "#1a1a1a",
    fontFamily: "'DM Sans', sans-serif", outline: "none",
  };

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ fontSize: 22, fontWeight: 600, color: "#f0f0f2", letterSpacing: -0.5 }}>Streamer Config</div>
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={exportCompanies} style={{ background: "none", border: "1px solid #2a2a32", borderRadius: 8, padding: "7px 14px", fontSize: 12, color: "#888", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>
              ↓ Export companies
            </button>
            <button onClick={importCompanies} style={{ background: "none", border: "1px solid #2a2a32", borderRadius: 8, padding: "7px 14px", fontSize: 12, color: "#888", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>
              ↑ Import companies
            </button>
          </div>
        </div>
        <div style={{ fontSize: 13, color: "#555", marginTop: 3 }}>Manage career pages to stream automatically</div>
      </div>

      {/* Companies list */}
      <div style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "20px 22px", marginBottom: 16 }}>

        {/* Add company form — at top */}
        <div style={{ marginBottom: 16, paddingBottom: 16, borderBottom: isDark ? "1px solid #1e1e24" : "1px solid #f0f0f4" }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: isDark ? "#666" : "#888", textTransform: "uppercase", letterSpacing: "0.4px", marginBottom: 8 }}>Add company</div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input value={newName} onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addCompany()}
              placeholder="Company name" style={{ ...inp, width: 160 }} />
            <select value={newIndustry} onChange={(e) => setNewIndustry(e.target.value)}
              style={{ ...inp, width: 170, cursor: "pointer", color: newIndustry ? (isDark ? "#f0f0f2" : "#1a1a1a") : (isDark ? "#555" : "#aaa") }}>
              <option value="">Industry (optional)</option>
              {industryOptions.map(ind => <option key={ind} value={ind}>{ind}</option>)}
            </select>
            <input value={newUrl} onChange={(e) => setNewUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addCompany()}
              placeholder="https://company.com/careers" style={{ ...inp, flex: 1, minWidth: 200 }} />
            <button onClick={addCompany}
              style={{ background: "var(--btn-primary)", border: "none", borderRadius: 8, padding: "9px 16px", fontSize: 13, color: "#fff", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", whiteSpace: "nowrap" }}>+ Add</button>
          </div>
          <div style={{ fontSize: 11, color: isDark ? "#555" : "#aaa", marginTop: 6 }}>
            Industry tags every job scraped from this company so job alerts match across companies in that sector.
          </div>
        </div>

        {/* Search + filter bar */}
        <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap", alignItems: "center" }}>
          <input
            value={companySearch}
            onChange={e => setCompanySearch(e.target.value)}
            placeholder="Search company name or URL…"
            style={{ ...inp, flex: 1, minWidth: 160 }}
          />
          <select value={companyIndustryFilter} onChange={e => setCompanyIndustryFilter(e.target.value)}
            style={{ ...inp, width: 170, cursor: "pointer", color: companyIndustryFilter ? (isDark ? "#f0f0f2" : "#1a1a1a") : (isDark ? "#555" : "#aaa") }}>
            <option value="">All industries</option>
            {industryOptions.map(ind => <option key={ind} value={ind}>{ind}</option>)}
          </select>
          <span style={{ fontSize: 12, color: isDark ? "#555" : "#aaa", whiteSpace: "nowrap" }}>
            {companies.filter(c =>
              (!companySearch || c.name.toLowerCase().includes(companySearch.toLowerCase()) || (c.url || "").toLowerCase().includes(companySearch.toLowerCase())) &&
              (!companyIndustryFilter || c.industry === companyIndustryFilter)
            ).length} / {companies.length}
          </span>
        </div>

        {loading ? <Spinner /> : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {companies
              .filter(c =>
                (!companySearch || c.name.toLowerCase().includes(companySearch.toLowerCase()) || (c.url || "").toLowerCase().includes(companySearch.toLowerCase())) &&
                (!companyIndustryFilter || c.industry === companyIndustryFilter)
              )
              .map((c) => (
              <div key={c.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 14px", background: isDark ? "#1C1C20" : "#f8f8fb", borderRadius: 8, border: isDark ? "1px solid #2a2a32" : "1px solid #e8e8f0" }}>
                {/* Logo */}
                <CompanyLogo name={c.name} sourceUrl={c.url} size={28} />
                {/* Name + URL */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, color: isDark ? "#f0f0f2" : "#1a1a1a" }}>{c.name}</div>
                  <div style={{ fontSize: 10, color: isDark ? "#555" : "#888", fontFamily: "'DM Mono', monospace", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.url}</div>
                </div>
                {/* Industry — inline editable */}
                <select
                  value={c.industry || ""}
                  onChange={(e) => updateIndustry(c.id, e.target.value)}
                  title="Industry — used to match jobs across companies in this industry for job alerts"
                  style={{ ...inp, padding: "4px 8px", fontSize: 11, width: 150, flexShrink: 0, cursor: "pointer", color: c.industry ? (isDark ? "#f0f0f2" : "#1a1a1a") : (isDark ? "#555" : "#aaa") }}
                >
                  <option value="">No industry</option>
                  {industryOptions.map(ind => <option key={ind} value={ind}>{ind}</option>)}
                </select>
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
                {/* Register as Org button */}
                <button
                  onClick={() => registerAsOrg(c)}
                  title="Register as organization (enables company page)"
                  style={{ background: "none", border: "none", color: "#555", cursor: "pointer", fontSize: 13, padding: "2px 6px", borderRadius: 5, fontFamily: "'DM Sans', sans-serif" }}
                  onMouseEnter={(e) => e.currentTarget.style.color = "#3DD68C"}
                  onMouseLeave={(e) => e.currentTarget.style.color = "#555"}
                >🏢</button>
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


// ── My Applications Page ─────────────────────────────────────────────────────
// ── Saved Jobs Page ──────────────────────────────────────────────────────────
// ── Companies Page ───────────────────────────────────────────────────────────
function CompaniesPage({ isDark = true, user, onSelectCompany }) {
  const [companies, setCompanies] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api("/organizations")
      .then(setCompanies)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const filtered = companies.filter(c =>
    c.name.toLowerCase().includes(search.toLowerCase()) ||
    (c.industry || "").toLowerCase().includes(search.toLowerCase())
  );

  const industries = [...new Set(companies.map(c => c.industry).filter(Boolean))];

  return (
    <div>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", letterSpacing: -0.5, marginBottom: 4 }}>Companies</h1>
        <p style={{ fontSize: 13, color: isDark ? "#666" : "#888" }}>{companies.length} companies hiring on JobStream</p>
      </div>

      {/* Search */}
      <div style={{ position: "relative", marginBottom: 20 }}>
        <span style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", fontSize: 14, color: "#888" }}>🔍</span>
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search companies or industries…"
          style={{ width: "100%", boxSizing: "border-box", background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 10, padding: "10px 12px 10px 36px", fontSize: 13, color: isDark ? "#f0f0f2" : "#1d1d1f", fontFamily: "'DM Sans', sans-serif", outline: "none" }}
        />
      </div>

      {loading && <Spinner />}

      {/* Grid */}
      {!loading && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 16 }}>
          {filtered.map(company => (
            <div
              key={company.id}
              onClick={() => {
                const slug = makeOrgSlug(company.name);
                window.history.pushState({}, "", `/companies/${slug}`);
                onSelectCompany(company.id);
              }}
              style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "20px", cursor: "pointer", transition: "border-color 0.15s, box-shadow 0.15s" }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = "#0071E3"; e.currentTarget.style.boxShadow = "0 4px 16px rgba(0,113,227,0.1)"; }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = isDark ? "#2a2a32" : "#e0e0e8"; e.currentTarget.style.boxShadow = "none"; }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
                <CompanyLogo name={company.name} sourceUrl={company.website} size={44} />
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 15, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{company.name}</div>
                  {company.industry && <div style={{ fontSize: 11, color: isDark ? "#666" : "#888" }}>{company.industry}</div>}
                </div>
              </div>
              {company.description && (
                <p style={{ fontSize: 12, color: isDark ? "#888" : "#666", lineHeight: 1.5, margin: 0, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                  {company.description}
                </p>
              )}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 12 }}>
                {company.size && <span style={{ fontSize: 11, color: isDark ? "#555" : "#aaa" }}>{company.size} employees</span>}
                <span style={{ fontSize: 11, color: "#0071E3", fontWeight: 500 }}>View jobs →</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {!loading && filtered.length === 0 && (
        <div style={{ textAlign: "center", padding: 60 }}>
          <div style={{ fontSize: 40, marginBottom: 16 }}>🏢</div>
          <div style={{ fontSize: 16, color: isDark ? "#666" : "#888" }}>No companies found</div>
        </div>
      )}
    </div>
  );
}


// ── Company Profile Page ──────────────────────────────────────────────────────
function CompanyProfilePage({ isDark = true, companyId, onApply, user, onAuthRequired, onBack, toast }) {
  const [company, setCompany] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState(null);
  const [savedIds, setSavedIds] = useState(new Set());

  useEffect(() => {
    if (!companyId) return;
    Promise.all([
      api(`/organizations/${companyId}`),
      api(`/organizations/${companyId}/jobs`),
    ]).then(([org, jobsData]) => {
      setCompany(org);
      setJobs(jobsData.jobs || []);
      setTotal(jobsData.total || 0);
    }).catch(() => {})
    .finally(() => setLoading(false));

    if (user) {
      api("/jobs/saved/ids").then(ids => setSavedIds(new Set(ids))).catch(() => {});
    }
  }, [companyId, user]);

  async function toggleSave(job) {
    if (!user) { onAuthRequired(); return; }
    const isSaved = savedIds.has(job.id);
    await api(`/jobs/${job.id}/save`, { method: isSaved ? "DELETE" : "POST" });
    setSavedIds(prev => {
      const next = new Set(prev);
      isSaved ? next.delete(job.id) : next.add(job.id);
      return next;
    });
    toast && toast(isSaved ? "Removed from saved" : "Job saved!");
  }

  if (loading) return <Spinner />;
  if (!company) return <div style={{ color: "#f87171", padding: 40 }}>Company not found</div>;

  const prevNames = (() => {
    try { return JSON.parse(company.previous_names || "[]"); } catch { return []; }
  })();

  return (
    <div style={{ maxWidth: 860 }}>
      {/* Back button */}
      <button
        onClick={onBack}
        style={{ background: "none", border: "none", cursor: "pointer", color: isDark ? "#666" : "#888", fontSize: 13, fontFamily: "'DM Sans', sans-serif", marginBottom: 20, display: "flex", alignItems: "center", gap: 6, padding: 0 }}
      >
        ← All companies
      </button>

      {/* Company header */}
      <div style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 16, padding: "28px 32px", marginBottom: 20 }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 20, marginBottom: 20 }}>
          <CompanyLogo name={company.name} sourceUrl={company.website} size={64} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <h1 style={{ fontSize: 24, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", letterSpacing: -0.5, marginBottom: 4 }}>{company.name}</h1>
            {prevNames.length > 0 && (
              <p style={{ fontSize: 12, color: isDark ? "#555" : "#aaa", marginBottom: 6 }}>
                Formerly: {prevNames.map(p => p.name || p).join(", ")}
              </p>
            )}
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {company.industry && <Chip isDark={isDark}>{company.industry}</Chip>}
              {company.size && <Chip isDark={isDark}>👥 {company.size}</Chip>}
              {company.country && <Chip isDark={isDark}>📍 {company.country}</Chip>}
            </div>
          </div>
          {company.website && (
            <a href={company.website} target="_blank" rel="noreferrer"
              style={{ background: isDark ? "#1e1e24" : "#f0f0f4", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 8, padding: "8px 16px", fontSize: 12, color: isDark ? "#888" : "#555", textDecoration: "none", whiteSpace: "nowrap" }}
            >
              🌐 Website
            </a>
          )}
        </div>

        {company.description && (
          <p style={{ fontSize: 14, color: isDark ? "#aaa" : "#555", lineHeight: 1.7, margin: 0 }}>
            {company.description}
          </p>
        )}
      </div>

      {/* Jobs section */}
      <div>
        <h2 style={{ fontSize: 17, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 16 }}>
          Open positions <span style={{ fontSize: 13, fontWeight: 400, color: isDark ? "#666" : "#888" }}>({total})</span>
        </h2>

        {jobs.length === 0 ? (
          <div style={{ textAlign: "center", padding: "40px 20px", background: isDark ? "#141416" : "#f8f8fb", borderRadius: 14, border: isDark ? "1px solid #2a2a32" : "1px solid #e8e8f0" }}>
            <div style={{ fontSize: 32, marginBottom: 12 }}>📭</div>
            <div style={{ fontSize: 14, color: isDark ? "#666" : "#888" }}>No open positions right now</div>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {jobs.map(job => (
              <JobCard
                key={job.id}
                job={job}
                onApply={onApply}
                onView={j => setExpandedId(expandedId === j.id ? null : j.id)}
                isExpanded={expandedId === job.id}
                isDark={isDark}
                user={user}
                onAuthRequired={onAuthRequired}
                isSaved={savedIds.has(job.id)}
                onToggleSave={toggleSave}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}


function SavedJobsPage({ isDark = true, user, onAuthRequired, onApply, toast }) {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState(null);

  useEffect(() => {
    if (!user) return;
    api("/jobs/saved")
      .then(setJobs)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [user]);

  async function removeSaved(job) {
    await api(`/jobs/${job.id}/save`, { method: "DELETE" });
    setJobs(prev => prev.filter(j => j.id !== job.id));
    toast && toast("Job removed from saved");
  }

  if (!user) return (
    <div style={{ textAlign: "center", padding: 60 }}>
      <div style={{ fontSize: 40, marginBottom: 16 }}>🔖</div>
      <div style={{ fontSize: 18, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 8 }}>Your saved jobs</div>
      <div style={{ fontSize: 14, color: isDark ? "#666" : "#888", marginBottom: 24 }}>Sign in to save jobs and apply later</div>
      <button onClick={onAuthRequired} style={{ background: "var(--btn-primary)", color: "#fff", border: "none", borderRadius: 10, padding: "10px 24px", fontSize: 14, fontWeight: 600, cursor: "pointer" }}>Sign in | Register</button>
    </div>
  );

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", letterSpacing: -0.5, marginBottom: 4 }}>Saved Jobs</h1>
        <p style={{ fontSize: 13, color: isDark ? "#666" : "#888" }}>{jobs.length} job{jobs.length !== 1 ? "s" : ""} saved</p>
      </div>

      {loading && <Spinner />}

      {!loading && jobs.length === 0 && (
        <div style={{ textAlign: "center", padding: 60 }}>
          <div style={{ fontSize: 40, marginBottom: 16 }}>🔖</div>
          <div style={{ fontSize: 16, fontWeight: 500, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 8 }}>No saved jobs yet</div>
          <div style={{ fontSize: 13, color: isDark ? "#666" : "#888" }}>Tap the bookmark icon on any job to save it</div>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {jobs.map((job) => (
          <div key={job.id} style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "18px 20px" }}>
            <div style={{ display: "flex", alignItems: "flex-start", gap: 14 }}>
              <CompanyLogo name={job.company} sourceUrl={job.source_url} size={42} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
                  <div>
                    <div style={{ fontSize: 16, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 2 }}>{job.title}</div>
                    <div style={{ fontSize: 12, color: isDark ? "#666" : "#888" }}>{job.company} · {job.location}</div>
                  </div>
                  <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
                    <button
                      onClick={() => onApply && onApply(job)}
                      style={{ background: "var(--btn-primary)", border: "none", borderRadius: 8, padding: "6px 14px", fontSize: 12, fontWeight: 500, color: "#fff", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}
                    >
                      Apply →
                    </button>
                    <button
                      onClick={() => removeSaved(job)}
                      title="Remove from saved"
                      style={{ background: "none", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 8, padding: "6px 10px", fontSize: 13, color: isDark ? "#666" : "#888", cursor: "pointer" }}
                    >
                      ✕
                    </button>
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
                  <Chip isDark={isDark}>📍 {job.location}</Chip>
                  <Chip isDark={isDark}>{job.job_type}</Chip>
                  {job.department && <Chip variant="accent" isDark={isDark}>{job.department}</Chip>}
                  {job.industry && <Chip variant="purple" isDark={isDark}>🏷 {job.industry}</Chip>}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}


function MyApplicationsPage({ isDark = true, user, onAuthRequired }) {
  const [apps, setApps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!user) return;
    api("/applications/mine")
      .then(setApps)
      .catch(() => setError("Failed to load applications"))
      .finally(() => setLoading(false));
  }, [user]);

  if (!user) return (
    <div style={{ textAlign: "center", padding: 60 }}>
      <div style={{ fontSize: 40, marginBottom: 16 }}>📨</div>
      <div style={{ fontSize: 18, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 8 }}>Track your applications</div>
      <div style={{ fontSize: 14, color: isDark ? "#666" : "#888", marginBottom: 24 }}>Sign in to see all the jobs you have applied to</div>
      <button onClick={onAuthRequired} style={{ background: "var(--btn-primary)", color: "#fff", border: "none", borderRadius: 10, padding: "10px 24px", fontSize: 14, fontWeight: 600, cursor: "pointer" }}>Sign in | Register</button>
    </div>
  );

  const statusColors = {
    new:        { bg: "rgba(0,113,227,0.1)",   color: "#0071E3" },
    reviewing:  { bg: "rgba(245,166,35,0.1)",  color: "#F5A623" },
    shortlisted:{ bg: "rgba(61,214,140,0.1)",  color: "#3DD68C" },
    rejected:   { bg: "rgba(245,101,101,0.1)", color: "#f87171" },
    hired:      { bg: "rgba(61,214,140,0.15)", color: "#3DD68C" },
  };

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", letterSpacing: -0.5, marginBottom: 4 }}>My Applications</h1>
        <p style={{ fontSize: 13, color: isDark ? "#666" : "#888" }}>{apps.length} application{apps.length !== 1 ? "s" : ""} submitted</p>
      </div>

      {loading && <Spinner />}
      {error && <div style={{ color: "#f87171", fontSize: 14 }}>{error}</div>}

      {!loading && apps.length === 0 && (
        <div style={{ textAlign: "center", padding: 60 }}>
          <div style={{ fontSize: 40, marginBottom: 16 }}>📭</div>
          <div style={{ fontSize: 16, fontWeight: 500, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 8 }}>No applications yet</div>
          <div style={{ fontSize: 13, color: isDark ? "#666" : "#888" }}>Jobs you apply to will appear here</div>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {apps.map((a) => {
          const sc = statusColors[a.status] || statusColors.new;
          return (
            <div key={a.id} style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "18px 20px", display: "flex", alignItems: "flex-start", gap: 14 }}>
              <CompanyLogo name={a.company || "?"} sourceUrl={a.source_url} size={42} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                  <div>
                    <div style={{ fontSize: 15, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 2 }}>{a.job_title || "Job"}</div>
                    <div style={{ fontSize: 12, color: isDark ? "#666" : "#888" }}>{a.company} · {a.location}</div>
                  </div>
                  <span style={{ background: sc.bg, color: sc.color, fontSize: 11, padding: "3px 10px", borderRadius: 20, fontWeight: 500, whiteSpace: "nowrap", textTransform: "capitalize" }}>
                    {a.status || "new"}
                  </span>
                </div>
                <div style={{ fontSize: 11, color: isDark ? "#444" : "#aaa", marginTop: 8, fontFamily: "'DM Mono', monospace" }}>
                  Applied {new Date(a.submitted_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}


// ── Profile Page ──────────────────────────────────────────────────────────────
function ProfilePage({ isDark = true, user, setUser, onAuthRequired, toast }) {
  const [form, setForm] = useState({
    full_name: user?.full_name || "",
    phone: "",
    location: "",
    bio: "",
    skills: "",
    linkedin_url: "",
    resume_url: "",
    years_experience: "",
  });
  const [loading, setLoading] = useState(false);
  const [fetching, setFetching] = useState(true);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  useEffect(() => {
    if (!user) return;
    api("/profile/me")
      .then((data) => {
        if (data) setForm((f) => ({ ...f, ...data, skills: Array.isArray(data.skills) ? data.skills.join(", ") : data.skills || "" }));
      })
      .catch(() => {})
      .finally(() => setFetching(false));
  }, [user]);

  async function handleSave(e) {
    e.preventDefault();
    setLoading(true);
    try {
      const payload = { ...form, skills: form.skills.split(",").map((s) => s.trim()).filter(Boolean) };
      await api("/profile/me", { method: "PUT", body: JSON.stringify(payload) });
      // Update user name in state
      const updatedUser = { ...user, full_name: form.full_name };
      localStorage.setItem("js_user", JSON.stringify(updatedUser));
      setUser(updatedUser);
      toast("Profile saved!");
    } catch (e) {
      toast("Failed to save profile");
    } finally {
      setLoading(false);
    }
  }

  if (!user) return (
    <div style={{ textAlign: "center", padding: 60 }}>
      <div style={{ fontSize: 40, marginBottom: 16 }}>👤</div>
      <div style={{ fontSize: 18, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 8 }}>Your profile</div>
      <div style={{ fontSize: 14, color: isDark ? "#666" : "#888", marginBottom: 24 }}>Sign in to create your candidate profile</div>
      <button onClick={onAuthRequired} style={{ background: "var(--btn-primary)", color: "#fff", border: "none", borderRadius: 10, padding: "10px 24px", fontSize: 14, fontWeight: 600, cursor: "pointer" }}>Sign in | Register</button>
    </div>
  );

  const inp = { width: "100%", boxSizing: "border-box", padding: "10px 14px", fontSize: 13, border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 10, background: isDark ? "#141416" : "#ffffff", color: isDark ? "#f0f0f2" : "#1d1d1f", fontFamily: "'DM Sans', sans-serif", outline: "none" };

  const Field = ({ label, field, placeholder, type = "text", hint }) => (
    <div style={{ marginBottom: 18 }}>
      <label style={{ fontSize: 11, fontWeight: 600, color: isDark ? "#888" : "#555", textTransform: "uppercase", letterSpacing: "0.5px", display: "block", marginBottom: 6 }}>{label}</label>
      <input type={type} value={form[field]} onChange={set(field)} placeholder={placeholder} style={inp} />
      {hint && <div style={{ fontSize: 11, color: isDark ? "#555" : "#aaa", marginTop: 4 }}>{hint}</div>}
    </div>
  );

  return (
    <div style={{ maxWidth: 640 }}>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1d1d1f", letterSpacing: -0.5, marginBottom: 4 }}>My Profile</h1>
        <p style={{ fontSize: 13, color: isDark ? "#666" : "#888" }}>Your profile is prefilled when you apply for jobs</p>
      </div>

      {fetching ? <Spinner /> : (
        <form onSubmit={handleSave}>
          {/* Avatar */}
          <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 28, padding: "16px 20px", background: isDark ? "#141416" : "#f8f8fb", borderRadius: 14, border: isDark ? "1px solid #2a2a32" : "1px solid #e8e8f0" }}>
            <div style={{ width: 56, height: 56, borderRadius: "50%", background: "var(--btn-primary)", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, fontWeight: 700, flexShrink: 0 }}>
              {(form.full_name || user.email || "?")[0].toUpperCase()}
            </div>
            <div>
              <div style={{ fontSize: 16, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f" }}>{form.full_name || user.full_name}</div>
              <div style={{ fontSize: 12, color: isDark ? "#666" : "#888" }}>{user.email}</div>
              <div style={{ fontSize: 11, color: "#0071E3", textTransform: "capitalize", marginTop: 2 }}>{user.role}</div>
            </div>
          </div>

          {/* Basic info */}
          <div style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "20px 22px", marginBottom: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 16 }}>Basic Information</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              <Field label="Full name" field="full_name" placeholder="Ada Okonkwo" />
              <Field label="Phone" field="phone" placeholder="+234 800 000 0000" type="tel" />
              <Field label="Location" field="location" placeholder="Lagos, Nigeria" />
              <Field label="Years of experience" field="years_experience" placeholder="3" type="number" />
            </div>
            <div style={{ marginBottom: 18 }}>
              <label style={{ fontSize: 11, fontWeight: 600, color: isDark ? "#888" : "#555", textTransform: "uppercase", letterSpacing: "0.5px", display: "block", marginBottom: 6 }}>Bio</label>
              <textarea value={form.bio} onChange={set("bio")} placeholder="A brief introduction about yourself..." style={{ ...inp, height: 80, resize: "vertical" }} />
            </div>
          </div>

          {/* Professional info */}
          <div style={{ background: isDark ? "#141416" : "#ffffff", border: isDark ? "1px solid #2a2a32" : "1px solid #e0e0e8", borderRadius: 14, padding: "20px 22px", marginBottom: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 16 }}>Professional Details</div>
            <Field label="Skills" field="skills" placeholder="React, Python, Project Management" hint="Separate skills with commas" />
            <Field label="LinkedIn URL" field="linkedin_url" placeholder="https://linkedin.com/in/yourname" />
            <Field label="CV / Resume link" field="resume_url" placeholder="https://drive.google.com/..." hint="Google Drive, Dropbox, or any public link" />
          </div>

          <button type="submit" disabled={loading} style={{ background: loading ? "#ccc" : "var(--btn-primary)", color: "#fff", border: "none", borderRadius: 10, padding: "12px 28px", fontSize: 14, fontWeight: 600, cursor: loading ? "default" : "pointer", fontFamily: "'DM Sans', sans-serif" }}>
            {loading ? "Saving…" : "Save profile"}
          </button>
        </form>
      )}
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

// ── App Shell ─────────────────────────────────────────────────────────────────
export default function App() {
  const [page, setPage] = useState("jobs");
  const [applyJob, setApplyJob] = useState(null);
  const [toast, setToast] = useState("");
  const [theme, setTheme] = useState("light");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [user, setUser] = useState(getStoredUser());
  const [showAuth, setShowAuth] = useState(false);
  const [selectedCompany, setSelectedCompany] = useState(null);
  const [showJobAlerts, setShowJobAlerts] = useState(false);
  const [navSettings, setNavSettings] = useState(null);

  // Load admin nav/theme settings on mount
  const [brandName, setBrandName] = useState(() => localStorage.getItem("js_brand_name") || "JobStream");
  const [brandLogo, setBrandLogo] = useState(() => localStorage.getItem("js_brand_logo") || "");

  useEffect(() => {
    Promise.all([
      fetch(`${API}/admin/settings/nav`).then(r => r.ok ? r.json() : null).catch(() => null),
      fetch(`${API}/admin/settings/theme`).then(r => r.ok ? r.json() : null).catch(() => null),
      fetch(`${API}/admin/settings/brand`).then(r => r.ok ? r.json() : null).catch(() => null),
    ]).then(([nav, thm, brand]) => {
      if (nav) setNavSettings(nav);
      if (thm) {
        const root = document.documentElement;
        if (thm.accent_color)    root.style.setProperty("--accent",      thm.accent_color);
        if (thm.btn_color_dark)  root.style.setProperty("--btn-dark",    thm.btn_color_dark);
        if (thm.btn_color_light) root.style.setProperty("--btn-light",   thm.btn_color_light);
        if (thm.bg_dark)         root.style.setProperty("--bg-dark",     thm.bg_dark);
        if (thm.bg_light)        root.style.setProperty("--bg-light",    thm.bg_light);
        // Set btn-primary based on current theme mode (dark/light)
        const isDarkMode = document.documentElement.classList.contains("dark")
          || localStorage.getItem("js_theme") === "dark";
        root.style.setProperty("--btn-primary",
          isDarkMode ? (thm.btn_color_dark || "#0071E3")
                     : (thm.btn_color_light || "#000000"));
      }
      if (brand?.name) { setBrandName(brand.name); localStorage.setItem("js_brand_name", brand.name); }
      if (brand?.logo_url !== undefined) { setBrandLogo(brand.logo_url || ""); localStorage.setItem("js_brand_logo", brand.logo_url || ""); }
    });
  }, []);
  const [myPermissions, setMyPermissions] = useState(new Set());
  const [resetToken, setResetToken] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("token") || "";
  });
  const [urlJobSlug, setUrlJobSlug] = useState(() => {
    // Support both /jobs/slug path AND ?job=slug query param (used in alert emails)
    const params = new URLSearchParams(window.location.search);
    const jobParam = params.get("job");
    if (jobParam) return jobParam;
    const path = window.location.pathname;
    const m = path.match(/^\/jobs\/(.+)/);
    return m ? m[1] : "";
  });
  const [urlOrgSlug, setUrlOrgSlug] = useState(() => {
    const path = window.location.pathname;
    const m = path.match(/^\/companies\/(.+)/);
    return m ? m[1] : "";
  });
  const isDark = theme === "dark";


  /** Check if current user has a permission */
  const can = (permission) => {
    if (!user) return false;
    if (user.role === "super_admin") return true;
    return myPermissions.has(permission);
  };

  const showToast = (msg) => { setToast(msg); };

  async function handleLogout() {
    const rt = localStorage.getItem("js_refresh_token");
    if (rt) await apiLogout(rt);
    clearAuth();
    setUser(null);
    showToast("Signed out successfully");
  }

  // All possible nav items with labels
  const ALL_NAV = [
    { id: "jobs",         icon: "💼", label: "Jobs" },
    { id: "companies",    icon: "🏢", label: "Companies" },
    { id: "postjob",      icon: "➕",  label: "Post a Job" },
    { id: "myapps",       icon: "📨", label: "My Applications" },
    { id: "saved",        icon: "🔖", label: "Saved Jobs" },
    { id: "employer",     icon: "🏢", label: "Employer" },
    { id: "applications", icon: "📋", label: "Applications" },
    { id: "ai",           icon: "✨",  label: "AI Tools" },
    { id: "billing",      icon: "💳",  label: "Billing" },
    { id: "analytics",    icon: "📊",  label: "Analytics" },
    { id: "workspace",    icon: "📊",  label: "Workspace" },
    { id: "admin",        icon: "⚙️",  label: "Admin" },
    { id: "scraper",      icon: "🤖",  label: "Streamer" },
  ];

  // Determine user group
  const isAdmin = user && ["super_admin","platform_admin"].includes(user.role);
  const isEmployer = user && ["org_owner","hr_admin","recruiter","hiring_manager","interviewer"].includes(user.role);
  const navGroup = !user ? "guest" : isAdmin ? "admin" : isEmployer ? "employer" : "candidate";

  // Default visibility per group
  const DEFAULT_NAV = {
    guest:     ["jobs", "companies", "postjob"],
    candidate: ["jobs", "companies", "myapps", "saved", "ai", "billing"],
    employer:  ["jobs", "companies", "employer", "applications", "analytics", "billing"],
    admin:     ["jobs", "companies", "myapps", "saved", "employer", "applications",
                "ai", "billing", "analytics", "workspace", "admin", "scraper"],
  };

  const allowedIds = new Set(navSettings?.[navGroup] || DEFAULT_NAV[navGroup] || []);
  if (isAdmin) { allowedIds.add("admin"); allowedIds.add("scraper"); }

  const NAV = ALL_NAV.filter(item => allowedIds.has(item.id));


  return (
    <div style={{ display: "grid", gridTemplateColumns: sidebarOpen ? "220px 1fr" : "52px 1fr", minHeight: "100vh", fontFamily: "'DM Sans', sans-serif", background: isDark ? "#0D0D0F" : "#f4f4f6", color: isDark ? "#f0f0f2" : "#1a1a1a", transition: "all 0.25s ease" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap');
        :root {
          --accent:      #0071E3;
          --btn-dark:    #0071E3;
          --btn-light:   #000000;
          --bg-dark:     #0a0a0c;
          --bg-light:    #f5f5f7;
          --btn-primary: #0071E3;
        }
        /* Switch btn-primary based on colour scheme */
        @media (prefers-color-scheme: light) {
          :root { --btn-primary: var(--btn-light, #000000); }
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes slideUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        .nav-item-wrap { overflow: visible !important; }
        .nav-item-wrap:hover .nav-tooltip { opacity: 1 !important; }
        input::placeholder, textarea::placeholder { color: #444; }
        ::-webkit-scrollbar { width: 6px; } ::-webkit-scrollbar-track { background: transparent; } ::-webkit-scrollbar-thumb { background: #2a2a32; border-radius: 3px; }
        select option { background: ${isDark ? "#141416" : "#ffffff"}; color: ${isDark ? "#f0f0f2" : "#111111"}; }
        select { color-scheme: ${isDark ? "dark" : "light"}; }
        /* Admin-controlled button colour — applied via CSS variables */
        .js-btn-primary {
          background: ${isDark ? "var(--btn-dark, #0071E3)" : "var(--btn-light, #000000)"} !important;
        }
        /* Mobile responsive fixes */
        @media (max-width: 480px) {
          .hide-on-xs { display: none !important; }
          .show-on-xs { display: inline !important; }
        }
        @media (min-width: 481px) {
          .show-on-xs { display: none !important; }
        }
        @media (max-width: 640px) {
          main { padding: 12px 12px 24px !important; }
        }
      `}</style>

      {/* Sidebar */}
      <aside style={{ background: isDark ? "#0f0f12" : "#ffffff", borderRight: isDark ? "1px solid #1e1e24" : "1px solid #e0e0e8", padding: sidebarOpen ? "20px 14px" : "12px 8px", display: "flex", flexDirection: "column", gap: 4, position: "sticky", top: 0, height: "100vh", transition: "all 0.25s ease", overflowY: "auto", overflowX: "hidden", width: sidebarOpen ? "220px" : "52px", minWidth: sidebarOpen ? "220px" : "52px", scrollbarWidth: "thin", scrollbarColor: isDark ? "#2a2a32 transparent" : "#d0d0d8 transparent" }}>

        {/* Burger only — logo moved to main top bar */}
        <div style={{ display: "flex", justifyContent: "center", marginBottom: 16, paddingTop: 4 }}>
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            title={sidebarOpen ? "Collapse menu" : "Expand menu"}
            style={{ background: "none", border: "none", cursor: "pointer", padding: 6, display: "flex", flexDirection: "column", gap: 4, alignItems: "center", justifyContent: "center", borderRadius: 6 }}
          >
            <span style={{ display: "block", width: 18, height: 2, background: isDark ? "#555" : "#aaa", borderRadius: 2 }} />
            <span style={{ display: "block", width: 18, height: 2, background: isDark ? "#555" : "#aaa", borderRadius: 2 }} />
            <span style={{ display: "block", width: 18, height: 2, background: isDark ? "#555" : "#aaa", borderRadius: 2 }} />
          </button>
        </div>



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

        {/* Streamer active status + version — admin only */}
        {isAdmin && (
          <>
            <div style={{ marginTop: "auto", background: isDark ? "#141416" : "#f0f0f4", border: isDark ? "1px solid #1e1e24" : "1px solid #d8d8e0", borderRadius: 10, padding: sidebarOpen ? "12px 14px" : "10px 6px", display: "flex", flexDirection: "column", alignItems: sidebarOpen ? "flex-start" : "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ width: 8, height: 8, background: "#3DD68C", borderRadius: "50%", display: "inline-block", flexShrink: 0, boxShadow: "0 0 6px #3DD68C" }} />
                {sidebarOpen && <span style={{ fontSize: 12, fontWeight: 500, color: isDark ? "#e0e0e0" : "#222" }}>Streamer active</span>}
              </div>
              {sidebarOpen && <div style={{ fontSize: 10, color: isDark ? "#aaa" : "#666", fontFamily: "'DM Mono', monospace", marginTop: 4 }}>Streams every 2 hours</div>}
            </div>
            {sidebarOpen && (
              <div style={{ textAlign: "center", fontSize: 9, color: isDark ? "#333" : "#bbb", fontFamily: "'DM Mono', monospace", marginTop: 8, letterSpacing: "0.5px" }}>JobStream v1.0.0</div>
            )}
          </>
        )}
      </aside>

      {/* Main */}
      <main style={{ padding: "16px 16px 28px", overflowY: "auto", maxHeight: "100vh", background: isDark ? "#0D0D0F" : "#f4f4f6", transition: "background 0.2s", position: "relative" }}>

        {/* Header row — brand left, auth controls right. Wraps on mobile instead of overlapping. */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          flexWrap: "wrap", gap: "10px 12px", marginBottom: 20,
        }}>
          {/* Brand */}
          <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0, flexShrink: 0 }}>
            {brandLogo
              ? <img src={brandLogo} alt={brandName} style={{ height: 26, width: "auto", objectFit: "contain", borderRadius: 6, flexShrink: 0 }} onError={e => { e.target.style.display = "none"; }} />
              : <div style={{ width: 26, height: 26, background: "var(--btn-primary)", borderRadius: 7, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, flexShrink: 0 }}>⚡</div>
            }
            <span style={{ fontSize: 15, fontWeight: 700, color: isDark ? "#f0f0f2" : "#1a1a1a", letterSpacing: -0.3, whiteSpace: "nowrap" }}>{brandName}</span>
          </div>

          {/* Auth controls — wraps below brand on narrow screens */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
            <button
              onClick={() => setShowJobAlerts(true)}
              title="Get job alerts by email"
              style={{ background: isDark ? "#1C1C20" : "#e8e8ec", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 20, padding: "5px 12px", fontSize: 12, color: isDark ? "#888" : "#555", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", whiteSpace: "nowrap" }}
            >
              🔔 <span className="hide-on-xs">Alerts</span>
            </button>

            <button
              onClick={() => setTheme(isDark ? "light" : "dark")}
              title={isDark ? "Switch to light mode" : "Switch to dark mode"}
              style={{ background: isDark ? "#1C1C20" : "#e8e8ec", border: isDark ? "1px solid #2a2a32" : "1px solid #d0d0d8", borderRadius: 20, padding: "5px 12px", fontSize: 12, color: isDark ? "#888" : "#555", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", whiteSpace: "nowrap" }}
            >
              {isDark ? "☀" : "●"} <span className="hide-on-xs">{isDark ? "Light" : "Dark"}</span>
            </button>

            {user ? (
              <UserMenu user={user} onLogout={handleLogout} isDark={isDark} setPage={setPage} />
            ) : (
              <button
                onClick={() => setShowAuth(true)}
                style={{ background: "var(--btn-primary)", border: "none", borderRadius: 8, padding: "8px 16px", fontSize: 13, fontWeight: 600, color: "#fff", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", boxShadow: "0 2px 8px rgba(0,113,227,0.3)", whiteSpace: "nowrap" }}
              >
                Sign in | Register
              </button>
            )}
          </div>
        </div>

        {isAdmin && <div style={{ marginBottom: 20 }}><StatsBar isDark={isDark} /></div>}
        {page === "jobs" && <JobsPage onApply={setApplyJob} toast={showToast} isDark={isDark} user={user} onAuthRequired={() => setShowAuth(true)} />}
        {page === "myapps" && <MyApplicationsPage isDark={isDark} user={user} onAuthRequired={() => setShowAuth(true)} />}
        {page === "saved" && <SavedJobsPage isDark={isDark} user={user} onAuthRequired={() => setShowAuth(true)} onApply={setApplyJob} toast={showToast} />}
        {page === "myalerts" && <MyAlertsPage isDark={isDark} user={user} onAuthRequired={() => setShowAuth(true)} toast={showToast} />}
        {page === "companies" && <CompaniesPage isDark={isDark} user={user} onSelectCompany={(id) => { setSelectedCompany(id); setPage("company"); }} />}
        {page === "company" && <CompanyProfilePage isDark={isDark} companyId={selectedCompany} onApply={setApplyJob} user={user} onAuthRequired={() => setShowAuth(true)} onBack={() => setPage("companies")} toast={showToast} />}
        {page === "profile" && <ProfilePage isDark={isDark} user={user} setUser={setUser} onAuthRequired={() => setShowAuth(true)} toast={showToast} />}
        {page === "scraper" && <ScraperPage toast={showToast} isDark={isDark} />}
        {page === "ai"        && <AIPage isDark={isDark} user={user} onAuthRequired={() => setShowAuth(true)} toast={showToast} />}
        {page === "billing"   && <BillingPage isDark={isDark} user={user} onAuthRequired={() => setShowAuth(true)} toast={showToast} />}
        {page === "analytics" && <AnalyticsPage isDark={isDark} user={user} onAuthRequired={() => setShowAuth(true)} toast={showToast} />}
        {page === "privacy"   && <PrivacyPage isDark={isDark} />}
        {page === "terms"     && <TermsPage isDark={isDark} />}
        {page === "employer"   && <EmployerPage isDark={isDark} user={user} onAuthRequired={() => setShowAuth(true)} toast={showToast} can={can} />}
        {page === "postjob"   && (user
          ? <EmployerPage isDark={isDark} user={user} onAuthRequired={() => setShowAuth(true)} toast={showToast} can={can} />
          : <div style={{ textAlign: "center", padding: 60 }}>
              <div style={{ fontSize: 36, marginBottom: 16 }}>➕</div>
              <div style={{ fontSize: 18, fontWeight: 600, color: isDark ? "#f0f0f2" : "#1d1d1f", marginBottom: 8 }}>Post a Job</div>
              <div style={{ fontSize: 14, color: isDark ? "#666" : "#888", marginBottom: 24 }}>Sign in or create an account to post jobs</div>
              <button onClick={() => setShowAuth(true)} style={{ background: "var(--btn-primary)", color: "#fff", border: "none", borderRadius: 10, padding: "11px 28px", fontSize: 14, fontWeight: 600, cursor: "pointer" }}>Sign in | Register</button>
            </div>
        )}
        {page === "workspace"  && <WorkspaceDashboardPage isDark={isDark} user={user} onAuthRequired={() => setShowAuth(true)} toast={showToast} />}
        {page === "admin"      && <AdminDashboardPage isDark={isDark} user={user} onAuthRequired={() => setShowAuth(true)} toast={showToast} />}
        {page === "applications" && <ApplicationsPage isDark={isDark} />}
      </main>

      {applyJob && <ApplyModal job={applyJob} onClose={() => setApplyJob(null)} onSuccess={showToast} user={user} />}
      {showAuth && <InlineAuthModal onClose={() => setShowAuth(false)} onSuccess={(u) => { setUser(u); showToast(`Welcome, ${u.full_name}!`); }} />}
      {urlJobSlug && <JobSlugHandler slug={urlJobSlug} isDark={isDark} user={user} onAuthRequired={() => setShowAuth(true)} toast={showToast} onClose={() => { setUrlJobSlug(""); window.history.replaceState({}, "", "/"); }} />}
      {urlOrgSlug && <OrgSlugHandler slug={urlOrgSlug} isDark={isDark} onBack={() => { setUrlOrgSlug(""); window.history.replaceState({}, "", "/companies"); setPage("companies"); }} onApply={setApplyJob} user={user} onAuthRequired={() => setShowAuth(true)} toast={showToast} />}
      {showJobAlerts && <JobAlertsModal isDark={isDark} user={user} onClose={() => setShowJobAlerts(false)} toast={showToast} />}
      {resetToken && <ResetPasswordModal token={resetToken} onClose={() => { setResetToken(""); window.history.replaceState({}, "", "/"); }} onSuccess={() => { setResetToken(""); window.history.replaceState({}, "", "/"); showToast("Password reset! Please sign in."); setShowAuth(true); }} />}
      {/* Footer */}
      <div style={{ marginTop: 40, paddingTop: 20, borderTop: isDark ? "1px solid #1e1e24" : "1px solid #e8e8f0", display: "flex", gap: 16, flexWrap: "wrap" }}>
        {[
          { label: "Privacy Policy", page: "privacy" },
          { label: "Terms of Service", page: "terms" },
        ].map(({ label, page }) => (
          <button key={page} onClick={() => setPage(page)} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 11, color: isDark ? "#444" : "#bbb", fontFamily: "'DM Sans', sans-serif", padding: 0 }}>
            {label}
          </button>
        ))}
        <span style={{ fontSize: 11, color: isDark ? "#333" : "#ccc", marginLeft: "auto" }}>
          &copy; {new Date().getFullYear()} JobStream
        </span>
      </div>

      {toast && <Toast msg={toast} onClose={() => setToast("")} />}
    </div>
  );
}
