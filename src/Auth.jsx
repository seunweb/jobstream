import { useState } from "react";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

// ── Auth API helpers ──────────────────────────────────────────────────────────
export async function apiLogin(email, password) {
  const res = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Login failed");
  }
  return res.json();
}

export async function apiRegister(email, password, full_name) {
  const res = await fetch(`${API}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, full_name }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Registration failed");
  }
  return res.json();
}

export async function apiLogout(refresh_token) {
  await fetch(`${API}/auth/logout`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token }),
  });
}

export async function apiRefreshToken(refresh_token) {
  const res = await fetch(`${API}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token }),
  });
  if (!res.ok) throw new Error("Session expired");
  return res.json();
}

// ── Auth storage helpers ──────────────────────────────────────────────────────
export function saveAuth(data) {
  localStorage.setItem("js_access_token", data.access_token);
  localStorage.setItem("js_refresh_token", data.refresh_token);
  localStorage.setItem("js_user", JSON.stringify(data.user));
}

export function clearAuth() {
  localStorage.removeItem("js_access_token");
  localStorage.removeItem("js_refresh_token");
  localStorage.removeItem("js_user");
}

export function getStoredUser() {
  try {
    return JSON.parse(localStorage.getItem("js_user"));
  } catch {
    return null;
  }
}

export function getAccessToken() {
  return localStorage.getItem("js_access_token");
}

// ── Input component ───────────────────────────────────────────────────────────
function Input({ label, type = "text", value, onChange, placeholder, required }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{ display: "block", fontSize: 12, fontWeight: 500, color: "#444", marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.4px" }}>
        {label}
      </label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        required={required}
        style={{
          width: "100%", boxSizing: "border-box",
          padding: "11px 14px", fontSize: 14,
          border: "1px solid #d0d0d8", borderRadius: 10,
          background: "#fff", color: "#1d1d1f",
          fontFamily: "'DM Sans', sans-serif", outline: "none",
          transition: "border-color 0.15s",
        }}
        onFocus={(e) => e.target.style.borderColor = "#0071E3"}
        onBlur={(e) => e.target.style.borderColor = "#d0d0d8"}
      />
    </div>
  );
}

// ── Login Page ────────────────────────────────────────────────────────────────
function LoginPage({ onSuccess, onSwitch }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const data = await apiLogin(email, password);
      saveAuth(data);
      onSuccess(data.user);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <h2 style={{ fontSize: 24, fontWeight: 700, color: "#1d1d1f", marginBottom: 6, letterSpacing: -0.5 }}>
        Welcome back
      </h2>
      <p style={{ fontSize: 14, color: "#666", marginBottom: 28 }}>
        Sign in to your JobStream account
      </p>

      {error && (
        <div style={{ background: "#fff0f0", border: "1px solid #f5c6c6", borderRadius: 8, padding: "10px 14px", marginBottom: 16, fontSize: 13, color: "#c0392b" }}>
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <Input label="Email address" type="email" value={email} onChange={setEmail} placeholder="you@email.com" required />
        <Input label="Password" type="password" value={password} onChange={setPassword} placeholder="••••••••" required />

        <button
          type="submit"
          disabled={loading}
          style={{
            width: "100%", padding: "12px", fontSize: 15, fontWeight: 600,
            background: loading ? "#ccc" : "#0071E3", color: "#fff",
            border: "none", borderRadius: 10, cursor: loading ? "default" : "pointer",
            fontFamily: "'DM Sans', sans-serif", transition: "background 0.15s",
            marginTop: 4,
          }}
        >
          {loading ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <p style={{ textAlign: "center", marginTop: 20, fontSize: 14, color: "#666" }}>
        Don't have an account?{" "}
        <span onClick={onSwitch} style={{ color: "#0071E3", cursor: "pointer", fontWeight: 500 }}>
          Create one
        </span>
      </p>
    </div>
  );
}

// ── Register Page ─────────────────────────────────────────────────────────────
function RegisterPage({ onSuccess, onSwitch }) {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const data = await apiRegister(email, password, fullName);
      saveAuth(data);
      onSuccess(data.user);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <h2 style={{ fontSize: 24, fontWeight: 700, color: "#1d1d1f", marginBottom: 6, letterSpacing: -0.5 }}>
        Create your account
      </h2>
      <p style={{ fontSize: 14, color: "#666", marginBottom: 28 }}>
        Join JobStream to start applying for jobs
      </p>

      {error && (
        <div style={{ background: "#fff0f0", border: "1px solid #f5c6c6", borderRadius: 8, padding: "10px 14px", marginBottom: 16, fontSize: 13, color: "#c0392b" }}>
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <Input label="Full name" value={fullName} onChange={setFullName} placeholder="Ada Okonkwo" required />
        <Input label="Email address" type="email" value={email} onChange={setEmail} placeholder="you@email.com" required />
        <Input label="Password" type="password" value={password} onChange={setPassword} placeholder="Min. 8 characters" required />

        <button
          type="submit"
          disabled={loading}
          style={{
            width: "100%", padding: "12px", fontSize: 15, fontWeight: 600,
            background: loading ? "#ccc" : "#0071E3", color: "#fff",
            border: "none", borderRadius: 10, cursor: loading ? "default" : "pointer",
            fontFamily: "'DM Sans', sans-serif", marginTop: 4,
          }}
        >
          {loading ? "Creating account…" : "Create account"}
        </button>
      </form>

      <p style={{ textAlign: "center", marginTop: 20, fontSize: 14, color: "#666" }}>
        Already have an account?{" "}
        <span onClick={onSwitch} style={{ color: "#0071E3", cursor: "pointer", fontWeight: 500 }}>
          Sign in
        </span>
      </p>
    </div>
  );
}

// ── Auth Modal ────────────────────────────────────────────────────────────────
export function AuthModal({ onClose, onSuccess }) {
  const [mode, setMode] = useState("login"); // login | register

  function handleSuccess(user) {
    onSuccess(user);
    onClose();
  }

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)",
        backdropFilter: "blur(4px)", display: "flex", alignItems: "center",
        justifyContent: "center", zIndex: 9000, padding: 20,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff", borderRadius: 20, padding: "36px 32px",
          width: "100%", maxWidth: 420, boxShadow: "0 20px 60px rgba(0,0,0,0.2)",
        }}
      >
        {/* Logo */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 28 }}>
          <div style={{ width: 32, height: 32, background: "#0071E3", borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>⚡</div>
          <span style={{ fontSize: 18, fontWeight: 700, color: "#1d1d1f" }}>JobStream</span>
        </div>

        {mode === "login" ? (
          <LoginPage onSuccess={handleSuccess} onSwitch={() => setMode("register")} />
        ) : (
          <RegisterPage onSuccess={handleSuccess} onSwitch={() => setMode("login")} />
        )}
      </div>
    </div>
  );
}

export default AuthModal;
