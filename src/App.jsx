import { useState, useEffect, useCallback, useRef } from "react";

// ── Config ──────────────────────────────────────────────────────────────────
const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function api(path, opts = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  if (res.status === 204) return null;
  return res.json();
}

// ── Colour palette per company initial ─────────────────────────────────────
const LOGO_COLORS = [
  { bg: "#1a1a2e", fg: "#7B6EF6" },
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

// ── Tiny components ─────────────────────────────────────────────────────────
function Chip({ children, variant = "default" }) {
  const styles = {
    default: { background: "#1e1e24", color: "#888", border: "1px solid #2a2a32" },
    accent:  { background: "rgba(123,110,246,0.15)", color: "#a99df8", border: "1px solid rgba(123,110,246,0.25)" },
    green:   { background: "rgba(61,214,140,0.1)",   color: "#3DD68C", border: "1px solid rgba(61,214,140,0.2)"  },
    amber:   { background: "rgba(245,166,35,0.1)",   color: "#F5A623", border: "1px solid rgba(245,166,35,0.2)"  },
    red:     { background: "rgba(245,101,101,0.1)",  color: "#f87171", border: "1px solid rgba(245,101,101,0.2)" },
  };
  return (
    <span style={{
      ...styles[variant],
      fontSize: 11, padding: "2px 9px", borderRadius: 20,
      fontFamily: "'DM Mono', monospace", whiteSpace: "nowrap",
    }}>
      {children}
    </span>
  );
}

function Spinner() {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 48 }}>
      <div style={{
        width: 28, height: 28, border: "2px solid #2a2a32",
        borderTopColor: "#7B6EF6", borderRadius: "50%",
        animation: "spin 0.7s linear infinite",
      }} />
    </div>
  );
}

function Toast({ msg, onClose }) {
  useEffect(() => { const t = setTimeout(onClose, 3500); return () => clearTimeout(t); }, [onClose]);
  return (
    <div style={{
      position: "fixed", bottom: 24, right: 24, zIndex: 999,
      background: "#1C1C20", border: "1px solid #3DD68C",
      color: "#3DD68C", padding: "12px 20px", borderRadius: 10,
      fontSize: 13, fontFamily: "'DM Sans', sans-serif",
      boxShadow: "0 4px 24px rgba(0,0,0,0.5)",
      animation: "slideUp 0.25s ease",
    }}>
      ✓ {msg}
    </div>
  );
}

// ── Apply Modal ──────────────────────────────────────────────────────────────
function ApplyModal({ job, onClose, onSuccess }) {
  const [form, setForm] = useState({ name: "", email: "", phone: "", resume_url: "", cover_note: "" });
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

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.75)",
      backdropFilter: "blur(4px)", display: "flex", alignItems: "center",
      justifyContent: "center", zIndex: 200, padding: 20,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "#141416", border: "1px solid #2a2a32", borderRadius: 16,
        width: "100%", maxWidth: 480, maxHeight: "90vh", overflowY: "auto",
      }}>
        <div style={{ padding: "22px 24px 16px", borderBottom: "1px solid #2a2a32", display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 600, color: "#f0f0f2" }}>{job.title}</div>
            <div style={{ fontSize: 12, color: "#666", marginTop: 3 }}>{job.company} · {job.location}</div>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", color: "#666", fontSize: 20, cursor: "pointer", lineHeight: 1 }}>✕</button>
        </div>
        <div style={{ padding: "20px 24px" }}>
          {error && <div style={{ background: "rgba(245,101,101,0.1)", border: "1px solid rgba(245,101,101,0.3)", color: "#f87171", borderRadius: 8, padding: "10px 14px", fontSize: 13, marginBottom: 16 }}>{error}</div>}
          {[
            { key: "name", label: "Full name *", placeholder: "Ada Okonkwo", type: "text" },
            { key: "email", label: "Email *", placeholder: "ada@email.com", type: "email" },
            { key: "phone", label: "Phone", placeholder: "+234 800 000 0000", type: "tel" },
            { key: "resume_url", label: "Resume / CV link", placeholder: "https://linkedin.com/in/…", type: "text" },
          ].map(({ key, label, placeholder, type }) => (
            <div key={key} style={{ marginBottom: 14 }}>
              <label style={{ fontSize: 10, color: "#666", display: "block", marginBottom: 5, textTransform: "uppercase", letterSpacing: "0.5px" }}>{label}</label>
              <input type={type} value={form[key]} onChange={set(key)} placeholder={placeholder}
                style={{ width: "100%", boxSizing: "border-box", background: "#1C1C20", border: "1px solid #2a2a32", borderRadius: 8, padding: "10px 12px", fontSize: 13, color: "#f0f0f2", fontFamily: "'DM Sans', sans-serif", outline: "none" }}
              />
            </div>
          ))}
          <div style={{ marginBottom: 14 }}>
            <label style={{ fontSize: 10, color: "#666", display: "block", marginBottom: 5, textTransform: "uppercase", letterSpacing: "0.5px" }}>Cover note</label>
            <textarea value={form.cover_note} onChange={set("cover_note")} placeholder="Why are you a great fit?"
              style={{ width: "100%", boxSizing: "border-box", background: "#1C1C20", border: "1px solid #2a2a32", borderRadius: 8, padding: "10px 12px", fontSize: 13, color: "#f0f0f2", fontFamily: "'DM Sans', sans-serif", outline: "none", height: 90, resize: "vertical" }}
            />
          </div>
        </div>
        <div style={{ padding: "14px 24px", borderTop: "1px solid #2a2a32", display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button onClick={onClose} style={{ background: "none", border: "1px solid #2a2a32", borderRadius: 8, padding: "8px 16px", fontSize: 13, color: "#888", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>Cancel</button>
          <button onClick={submit} disabled={loading} style={{ background: "#7B6EF6", border: "none", borderRadius: 8, padding: "8px 20px", fontSize: 13, fontWeight: 500, color: "#fff", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", opacity: loading ? 0.6 : 1 }}>
            {loading ? "Submitting…" : "Submit →"}
          </button>
        </div>
      </div>
    </div>
  );
}


// ── Job Detail Modal ─────────────────────────────────────────────────────────
function JobDetailModal({ job, onClose, onApply }) {
  const lc = logoColor(job.company);

  return (
    <div onClick={onClose} style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.75)",
      backdropFilter: "blur(4px)", display: "flex", alignItems: "center",
      justifyContent: "center", zIndex: 200, padding: 20,
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        background: "#141416", border: "1px solid #2a2a32", borderRadius: 16,
        width: "100%", maxWidth: 620, maxHeight: "90vh", overflowY: "auto",
      }}>
        {/* Header */}
        <div style={{ padding: "24px 24px 20px", borderBottom: "1px solid #2a2a32" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
            <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
              <div style={{ width: 48, height: 48, borderRadius: 12, background: lc.bg, color: lc.fg, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16, fontWeight: 600, flexShrink: 0 }}>
                {initials(job.company)}
              </div>
              <div>
                <div style={{ fontSize: 18, fontWeight: 600, color: "#f0f0f2", letterSpacing: -0.3 }}>{job.title}</div>
                <div style={{ fontSize: 13, color: "#666", marginTop: 3 }}>{job.company}</div>
              </div>
            </div>
            <button onClick={onClose} style={{ background: "none", border: "none", color: "#666", fontSize: 20, cursor: "pointer" }}>✕</button>
          </div>

          {/* Meta chips */}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Chip>📍 {job.location}</Chip>
            <Chip>{job.job_type}</Chip>
            {job.salary && <Chip>💰 {job.salary}</Chip>}
            <Chip variant="accent">{job.department}</Chip>
          </div>
        </div>

        {/* Body */}
        <div style={{ padding: "20px 24px" }}>
          {/* Posted date */}
          <div style={{ fontSize: 11, color: "#555", fontFamily: "'DM Mono', monospace", marginBottom: 20 }}>
            🤖 Auto-scraped · {job.scraped_at ? new Date(job.scraped_at).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }) : "—"}
          </div>

          {/* Description */}
          {job.description ? (
            <div>
              <div style={{ fontSize: 12, color: "#666", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: 10, fontWeight: 500 }}>About this role</div>
              <div style={{ fontSize: 13, color: "#b0b0c0", lineHeight: 1.8, whiteSpace: "pre-wrap" }}>{job.description}</div>
            </div>
          ) : (
            <div style={{ background: "#1C1C20", border: "1px solid #2a2a32", borderRadius: 10, padding: "20px 24px", textAlign: "center" }}>
              <div style={{ fontSize: 24, marginBottom: 8 }}>📄</div>
              <div style={{ fontSize: 13, color: "#666", marginBottom: 6 }}>Full description on company site</div>
              <a href={job.apply_url} target="_blank" rel="noreferrer"
                style={{ fontSize: 12, color: "#7B6EF6", textDecoration: "none" }}>
                View original posting →
              </a>
            </div>
          )}

          {/* Original link */}
          {job.apply_url && (
            <div style={{ marginTop: 20, padding: "12px 16px", background: "#1C1C20", borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={{ fontSize: 12, color: "#666" }}>Original job posting</span>
              <a href={job.apply_url} target="_blank" rel="noreferrer"
                style={{ fontSize: 12, color: "#7B6EF6", textDecoration: "none" }}>
                {new URL(job.apply_url.startsWith("http") ? job.apply_url : "https://" + job.apply_url).hostname} →
              </a>
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{ padding: "16px 24px", borderTop: "1px solid #2a2a32", display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button onClick={onClose} style={{ background: "none", border: "1px solid #2a2a32", borderRadius: 8, padding: "9px 16px", fontSize: 13, color: "#888", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>
            Close
          </button>
          <button onClick={() => { onClose(); onApply(job); }} style={{ background: "#7B6EF6", border: "none", borderRadius: 8, padding: "9px 20px", fontSize: 13, fontWeight: 500, color: "#fff", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>
            Apply now →
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Job Card ─────────────────────────────────────────────────────────────────
function JobCard({ job, onApply, onView, isExpanded }) {
  const lc = logoColor(job.company);
  const isNew = (() => {
    try { return (Date.now() - new Date(job.created_at).getTime()) < 86400000 * 2; } catch { return false; }
  })();

  const postedDate = job.scraped_at
    ? new Date(job.scraped_at).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" })
    : "—";

  return (
    <div style={{
      background: "#141416", border: `1px solid ${isExpanded ? "#7B6EF6" : "#2a2a32"}`, borderRadius: 14,
      overflow: "hidden", transition: "border-color 0.15s",
    }}>
      {/* Card header - always visible */}
      <div
        style={{ padding: "18px 20px", cursor: "pointer" }}
        onClick={() => onView(job)}
        onMouseEnter={(e) => e.currentTarget.style.background = "#1a1a1e"}
        onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
      >
        <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
          <div style={{ width: 42, height: 42, borderRadius: 10, background: lc.bg, color: lc.fg, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 600, flexShrink: 0 }}>
            {initials(job.company)}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: 500, color: "#f0f0f2", marginBottom: 2 }}>{job.title}</div>
            <div style={{ fontSize: 12, color: "#666" }}>{job.company}</div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
            {isNew && <Chip variant="green">New</Chip>}
            <span style={{ fontSize: 14, color: "#555", transition: "transform 0.2s", display: "inline-block", transform: isExpanded ? "rotate(180deg)" : "rotate(0deg)" }}>⌄</span>
          </div>
        </div>

        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 14 }}>
          <Chip>📍 {job.location}</Chip>
          <Chip>{job.job_type}</Chip>
          {job.salary && <Chip>💰 {job.salary}</Chip>}
          <Chip variant="accent">{job.department}</Chip>
        </div>

        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 14, paddingTop: 14, borderTop: "1px solid #1e1e24" }}>
          <span style={{ fontSize: 11, color: "#555", fontFamily: "'DM Mono', monospace" }}>
            Posted on {postedDate}
          </span>
          <button onClick={(e) => { e.stopPropagation(); onApply(job); }} style={{
            background: "#7B6EF6", border: "none", borderRadius: 8,
            padding: "7px 16px", fontSize: 12, fontWeight: 500, color: "#fff",
            cursor: "pointer", fontFamily: "'DM Sans', sans-serif",
          }}
            onMouseEnter={(e) => e.currentTarget.style.background = "#9D94F8"}
            onMouseLeave={(e) => e.currentTarget.style.background = "#7B6EF6"}
          >
            Apply now →
          </button>
        </div>
      </div>

      {/* Inline expanded detail */}
      {isExpanded && (
        <div style={{ borderTop: "1px solid #2a2a32", padding: "20px 24px", background: "#111113" }}>
          {/* Description */}
          <div style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 11, color: "#555", textTransform: "uppercase", letterSpacing: "0.5px", fontWeight: 500, marginBottom: 12 }}>About this role</div>
            {job.description && job.description.trim() ? (
              <div style={{ fontSize: 13, color: "#b0b0c0", lineHeight: 1.9, whiteSpace: "pre-wrap" }}>{job.description.trim()}</div>
            ) : (
              <div style={{ fontSize: 13, color: "#555", lineHeight: 1.8 }}>
                This job was scraped from the company career page. The full description is available on their website — click <strong style={{ color: "#a99df8" }}>Apply on company website</strong> below to view it.
              </div>
            )}
          </div>

          {/* Action buttons */}
          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", paddingTop: 16, borderTop: "1px solid #2a2a32" }}>
            <button onClick={() => onView(job)} style={{ background: "none", border: "1px solid #2a2a32", borderRadius: 8, padding: "9px 16px", fontSize: 13, color: "#888", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>
              Close
            </button>
            {job.apply_url && (
              <a href={job.apply_url} target="_blank" rel="noreferrer" style={{ background: "#1e1e2e", border: "1px solid rgba(123,110,246,0.4)", borderRadius: 8, padding: "9px 16px", fontSize: 13, color: "#a99df8", cursor: "pointer", fontFamily: "'DM Sans', sans-serif", textDecoration: "none" }}>
                Apply on company website →
              </a>
            )}
            <button onClick={() => onApply(job)} style={{ background: "#7B6EF6", border: "none", borderRadius: 8, padding: "9px 20px", fontSize: 13, fontWeight: 500, color: "#fff", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>
              Apply now →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Pages ─────────────────────────────────────────────────────────────────────
function JobsPage({ onApply, toast }) {
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
          <div style={{ fontSize: 13, color: "#555", marginTop: 3 }}>{total} live jobs from scraped career pages</div>
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
            background: scraping ? "#1e1e24" : "#7B6EF6", border: "1px solid #3a3a42",
            borderRadius: 9, padding: "8px 16px", fontSize: 12, color: scraping ? "#666" : "#fff",
            cursor: scraping ? "default" : "pointer", fontFamily: "'DM Sans', sans-serif", display: "flex", alignItems: "center", gap: 6,
          }}>
            {scraping ? "Scraping…" : "⟳ Scrape now"}
          </button>
        </div>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: 10, marginBottom: 20, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 200, position: "relative" }}>
          <span style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", color: "#555", fontSize: 14 }}>🔍</span>
          <input value={search} onChange={(e) => onSearch(e.target.value)} placeholder="Search roles, companies…"
            style={{ width: "100%", boxSizing: "border-box", background: "#141416", border: "1px solid #2a2a32", borderRadius: 9, padding: "9px 12px 9px 34px", fontSize: 13, color: "#f0f0f2", fontFamily: "'DM Sans', sans-serif", outline: "none" }}
          />
        </div>
        {[
          { val: jobType, set: (v) => { setJobType(v); load(search, v, dept); }, opts: ["", "Full-time", "Part-time", "Contract", "Remote"], label: "Type" },
          { val: dept, set: (v) => { setDept(v); load(search, jobType, v); }, opts: ["", "Engineering", "Design", "Marketing", "Product", "Operations"], label: "Department" },
        ].map(({ val, set, opts, label }) => (
          <select key={label} value={val} onChange={(e) => set(e.target.value)}
            style={{ background: "#141416", border: "1px solid #2a2a32", borderRadius: 9, padding: "9px 12px", fontSize: 13, color: val ? "#f0f0f2" : "#666", fontFamily: "'DM Sans', sans-serif", outline: "none", cursor: "pointer" }}>
            {opts.map((o) => <option key={o} value={o}>{o || `All ${label}s`}</option>)}
          </select>
        ))}
      </div>

      {error && (
        <div style={{ background: "rgba(245,101,101,0.08)", border: "1px solid rgba(245,101,101,0.25)", borderRadius: 10, padding: "16px 20px", marginBottom: 20 }}>
          <div style={{ color: "#f87171", fontSize: 14, fontWeight: 500, marginBottom: 6 }}>Backend not connected</div>
          <div style={{ color: "#888", fontSize: 12 }}>{error}</div>
          <div style={{ color: "#555", fontSize: 11, marginTop: 8, fontFamily: "'DM Mono', monospace" }}>
            Run: <span style={{ color: "#7B6EF6" }}>uvicorn main:app --reload --port 8000</span>
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
          {jobs.map((j) => <JobCard key={j.id} job={j} onApply={onApply} onView={(job) => setExpandedId(expandedId === job.id ? null : job.id)} isExpanded={expandedId === j.id} />)}
        </div>
      )}
    </div>
  );
}

function ScraperPage({ toast }) {
  const [companies, setCompanies] = useState([]);
  const [history, setHistory] = useState([]);
  const [newName, setNewName] = useState("");
  const [newUrl, setNewUrl] = useState("");
  const [loading, setLoading] = useState(true);
  const [scrapingId, setScrapingId] = useState(null);

  async function load() {
    try {
      const [c, h] = await Promise.all([api("/companies"), api("/scrape/history")]);
      setCompanies(c); setHistory(h);
    } catch {}
    finally { setLoading(false); }
  }

  useEffect(() => { load(); }, []);

  async function addCompany() {
    if (!newName || !newUrl) return;
    try {
      await api("/companies", { method: "POST", body: JSON.stringify({ name: newName, url: newUrl }) });
      setNewName(""); setNewUrl(""); load();
      toast(`Added ${newName}`);
    } catch (e) { toast("Failed: " + e.message); }
  }

  async function removeCompany(id, name) {
    await api(`/companies/${id}`, { method: "DELETE" });
    load(); toast(`Removed ${name}`);
  }

  async function scrapeOne(id, name) {
    setScrapingId(id);
    try {
      await api(`/scrape/${id}`, { method: "POST" });
      toast(`Scraping ${name}\u2026 jobs will appear shortly.`);
      setTimeout(load, 5000);
    } catch { toast(`Failed to scrape ${name}`); }
    finally { setScrapingId(null); }

  async function forceRescrape(id, name) {
    setScrapingId(id);
    try {
      await api(`/scrape/${id}/force`, { method: "POST" });
      toast(`Force rescraping ${name}... old jobs cleared, fetching fresh descriptions.`);
      setTimeout(load, 10000);
    } catch (e) {
      toast(`Force rescrape failed: ${e.message}`);
    } finally {
      setScrapingId(null);
    }
  }
  }

  const inputStyle = { background: "#141416", border: "1px solid #2a2a32", borderRadius: 8, padding: "9px 12px", fontSize: 13, color: "#f0f0f2", fontFamily: "'DM Sans', sans-serif", outline: "none" };

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize: 22, fontWeight: 600, color: "#f0f0f2", letterSpacing: -0.5 }}>Scraper Config</div>
        <div style={{ fontSize: 13, color: "#555", marginTop: 3 }}>Manage career pages to scrape automatically</div>
      </div>

      {/* Companies */}
      <div style={{ background: "#141416", border: "1px solid #2a2a32", borderRadius: 14, padding: "20px 22px", marginBottom: 16 }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: "#f0f0f2", marginBottom: 16 }}>Tracked companies</div>
        {loading ? <Spinner /> : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 16 }}>
            {companies.map((c) => (
              <div key={c.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 14px", background: "#1C1C20", borderRadius: 8, border: "1px solid #2a2a32" }}>
                <div style={{ width: 28, height: 28, borderRadius: 6, ...logoColor(c.name), display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 600, background: logoColor(c.name).bg, color: logoColor(c.name).fg }}>
                  {initials(c.name)}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, color: "#f0f0f2" }}>{c.name}</div>
                  <div style={{ fontSize: 10, color: "#555", fontFamily: "'DM Mono', monospace" }}>{c.url}</div>
                </div>
                <button
                  onClick={() => scrapeOne(c.id, c.name)}
                  disabled={scrapingId === c.id}
                  title="Scrape this company only"
                  style={{ background: scrapingId === c.id ? "#1e1e24" : "rgba(123,110,246,0.15)", border: "1px solid rgba(123,110,246,0.3)", borderRadius: 6, padding: "4px 10px", fontSize: 11, color: scrapingId === c.id ? "#555" : "#a99df8", cursor: scrapingId === c.id ? "default" : "pointer", fontFamily: "'DM Sans', sans-serif", whiteSpace: "nowrap" }}
                >
                  {scrapingId === c.id ? "Scraping\u2026" : "\u27f3 Scrape"}
                </button>
                <button
                  onClick={() => forceRescrape(c.id, c.name)}
                  disabled={scrapingId === c.id}
                  title="Clear existing jobs and rescrape fresh with descriptions"
                  style={{ background: "rgba(245,101,101,0.1)", border: "1px solid rgba(245,101,101,0.25)", borderRadius: 6, padding: "4px 10px", fontSize: 11, color: "#f87171", cursor: scrapingId === c.id ? "default" : "pointer", fontFamily: "'DM Sans', sans-serif", whiteSpace: "nowrap" }}
                >
                  Force
                </button>
                <button onClick={() => removeCompany(c.id, c.name)} style={{ background: "none", border: "none", color: "#555", cursor: "pointer", fontSize: 16, lineHeight: 1, padding: 4 }}
                  onMouseEnter={(e) => e.currentTarget.style.color = "#f87171"}
                  onMouseLeave={(e) => e.currentTarget.style.color = "#555"}
                >✕</button>
              </div>
            ))}
          </div>
        )}
        <div style={{ display: "flex", gap: 8 }}>
          <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Company name" style={{ ...inputStyle, width: 140 }} />
          <input value={newUrl} onChange={(e) => setNewUrl(e.target.value)} placeholder="https://company.com/careers" style={{ ...inputStyle, flex: 1 }} />
          <button onClick={addCompany} style={{ background: "#7B6EF6", border: "none", borderRadius: 8, padding: "9px 16px", fontSize: 13, color: "#fff", cursor: "pointer", fontFamily: "'DM Sans', sans-serif" }}>+ Add</button>
        </div>
      </div>

      {/* Scrape history */}
      <div style={{ background: "#141416", border: "1px solid #2a2a32", borderRadius: 14, padding: "20px 22px" }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: "#f0f0f2", marginBottom: 16 }}>Scrape history</div>
        {history.length === 0 ? (
          <div style={{ color: "#444", fontSize: 12, fontFamily: "'DM Mono', monospace" }}>No scrape runs yet. Trigger one from the job board.</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {history.map((r) => (
              <div key={r.id} style={{ display: "flex", gap: 12, alignItems: "center", padding: "8px 0", borderBottom: "1px solid #1e1e24", fontSize: 12 }}>
                <Chip variant={r.status === "success" ? "green" : r.status === "running" ? "accent" : "red"}>{r.status}</Chip>
                <span style={{ color: "#888", fontFamily: "'DM Mono', monospace", flex: 1 }}>{new Date(r.started_at).toLocaleString()}</span>
                <span style={{ color: "#555" }}>{r.jobs_found} found · <span style={{ color: "#3DD68C" }}>+{r.jobs_new} new</span></span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ApplicationsPage() {
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
            <div key={a.id} style={{ background: "#141416", border: "1px solid #2a2a32", borderRadius: 12, padding: "16px 18px", display: "flex", gap: 14, alignItems: "flex-start" }}>
              <div style={{ width: 36, height: 36, borderRadius: 8, background: "#1e1e2e", color: "#7B6EF6", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 600, flexShrink: 0 }}>
                {initials(a.name)}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
                  <span style={{ fontSize: 14, fontWeight: 500, color: "#f0f0f2" }}>{a.name}</span>
                  <Chip variant={statusVariant[a.status] || "default"}>{a.status}</Chip>
                </div>
                <div style={{ fontSize: 12, color: "#666" }}>{a.email}</div>
                <div style={{ fontSize: 11, color: "#444", marginTop: 4, fontFamily: "'DM Mono', monospace" }}>
                  {a.job_title} · {new Date(a.submitted_at).toLocaleDateString()}
                </div>
              </div>
              {a.resume_url && (
                <a href={a.resume_url} target="_blank" rel="noreferrer" style={{ fontSize: 11, color: "#7B6EF6", textDecoration: "none", whiteSpace: "nowrap" }}>Resume →</a>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Stats bar ─────────────────────────────────────────────────────────────────
function StatsBar() {
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
        <div key={label} style={{ background: "#141416", border: "1px solid #2a2a32", borderRadius: 12, padding: "14px 16px" }}>
          <div style={{ fontSize: typeof val === "number" ? 24 : 15, fontWeight: 600, color: "#f0f0f2", letterSpacing: -0.5 }}>{val}</div>
          <div style={{ fontSize: 11, color: "#555", marginTop: 4 }}>{label}</div>
        </div>
      ))}
    </div>
  );
}

// ── App Shell ─────────────────────────────────────────────────────────────────
export default function App() {
  const [page, setPage] = useState("jobs");
  const [applyJob, setApplyJob] = useState(null);
  const [toast, setToast] = useState("");

  const showToast = (msg) => { setToast(msg); };

  const NAV = [
    { id: "jobs", icon: "💼", label: "Job Board" },
    { id: "scraper", icon: "🤖", label: "Scraper" },
    { id: "applications", icon: "📋", label: "Applications" },
  ];

  return (
    <div style={{ display: "grid", gridTemplateColumns: "220px 1fr", minHeight: "100vh", fontFamily: "'DM Sans', sans-serif", background: "#0D0D0F", color: "#f0f0f2" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes slideUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        input::placeholder, textarea::placeholder { color: #444; }
        ::-webkit-scrollbar { width: 6px; } ::-webkit-scrollbar-track { background: transparent; } ::-webkit-scrollbar-thumb { background: #2a2a32; border-radius: 3px; }
      `}</style>

      {/* Sidebar */}
      <aside style={{ background: "#0f0f12", borderRight: "1px solid #1e1e24", padding: "22px 14px", display: "flex", flexDirection: "column", gap: 4, position: "sticky", top: 0, height: "100vh" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 10px", marginBottom: 20 }}>
          <div style={{ width: 30, height: 30, background: "#7B6EF6", borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 15 }}>⚡</div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600, letterSpacing: -0.3 }}>JobStream</div>
            <div style={{ fontSize: 9, color: "#444", fontFamily: "'DM Mono', monospace" }}>MVP v0.1</div>
          </div>
        </div>

        {NAV.map(({ id, icon, label }) => (
          <button key={id} onClick={() => setPage(id)} style={{
            display: "flex", alignItems: "center", gap: 10, padding: "9px 12px",
            borderRadius: 9, border: "none", cursor: "pointer", fontSize: 13,
            fontFamily: "'DM Sans', sans-serif", textAlign: "left", transition: "all 0.15s",
            background: page === id ? "rgba(123,110,246,0.15)" : "none",
            color: page === id ? "#a99df8" : "#666",
          }}>
            <span style={{ fontSize: 15 }}>{icon}</span> {label}
          </button>
        ))}

        <div style={{ marginTop: "auto", background: "#141416", border: "1px solid #1e1e24", borderRadius: 10, padding: "12px 14px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
            <span style={{ width: 6, height: 6, background: "#3DD68C", borderRadius: "50%", display: "inline-block", animation: "spin 3s linear infinite" }} />
            <span style={{ fontSize: 12, fontWeight: 500, color: "#f0f0f2" }}>Scraper active</span>
          </div>
          <div style={{ fontSize: 10, color: "#444", fontFamily: "'DM Mono', monospace" }}>Runs every 2 hours</div>
        </div>
      </aside>

      {/* Main */}
      <main style={{ padding: "28px 32px", overflowY: "auto", maxHeight: "100vh" }}>
        <StatsBar />
        {page === "jobs" && <JobsPage onApply={setApplyJob} toast={showToast} />}
        {page === "scraper" && <ScraperPage toast={showToast} />}
        {page === "applications" && <ApplicationsPage />}
      </main>

      {applyJob && <ApplyModal job={applyJob} onClose={() => setApplyJob(null)} onSuccess={showToast} />}
      {toast && <Toast msg={toast} onClose={() => setToast("")} />}
    </div>
  );
}
