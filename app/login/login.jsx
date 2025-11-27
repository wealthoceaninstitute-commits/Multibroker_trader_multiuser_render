"use client";

import { useState, useEffect } from "react";

export default function LoginPage() {
  const [tab, setTab] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);

  // If already logged in → redirect to trade
  useEffect(() => {
    const token = localStorage.getItem("woi_token");
    if (token) window.location.href = "/trade";
  }, []);

  async function handleLogin() {
    setLoading(true);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE}/users/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      const data = await res.json();
      if (!data.success) {
        alert(data.detail || "Invalid login");
        setLoading(false);
        return;
      }

      localStorage.setItem("woi_token", data.token);
      localStorage.setItem("woi_username", data.username);

      window.location.href = "/trade";
    } catch (err) {
      alert("Login failed");
    }
    setLoading(false);
  }

  async function handleRegister() {
    setLoading(true);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE}/users/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, email }),
      });

      const data = await res.json();
      if (!data.success) {
        alert(data.detail || "Registration failed");
        setLoading(false);
        return;
      }

      localStorage.setItem("woi_token", data.token);
      localStorage.setItem("woi_username", data.username);

      window.location.href = "/trade";
    } catch (err) {
      alert("Registration failed");
    }
    setLoading(false);
  }

  return (
    <div style={{
      background: "#f7f9fc",
      minHeight: "100vh",
      display: "flex",
      justifyContent: "center",
      alignItems: "center",
      padding: "20px"
    }}>

      <div style={{
        width: "450px",
        background: "white",
        padding: "40px",
        borderRadius: "16px",
        boxShadow: "0 8px 25px rgba(0,0,0,0.1)",
        borderTop: "6px solid #0B5ED7"
      }}>
        
        <h2 style={{ textAlign: "center", marginBottom: "5px", color: "#0B5ED7" }}>
          Wealth Ocean Institute
        </h2>
        <p style={{ textAlign: "center", marginBottom: "30px", color: "#555" }}>
          Multi-broker, multi-user trading platform
        </p>

        <div style={{
          display: "flex",
          justifyContent: "center",
          marginBottom: "25px"
        }}>
          <button
            onClick={() => setTab("login")}
            style={{
              padding: "10px 25px",
              borderRadius: "8px",
              border: "none",
              marginRight: "10px",
              background: tab === "login" ? "#0B5ED7" : "#e2e6ea",
              color: tab === "login" ? "#fff" : "#333",
              fontWeight: "600",
              cursor: "pointer"
            }}>
            Login
          </button>

          <button
            onClick={() => setTab("register")}
            style={{
              padding: "10px 25px",
              borderRadius: "8px",
              border: "none",
              background: tab === "register" ? "#0B5ED7" : "#e2e6ea",
              color: tab === "register" ? "#fff" : "#333",
              fontWeight: "600",
              cursor: "pointer"
            }}>
            Create Account
          </button>
        </div>

        <label className="label">Username</label>
        <input
          className="input"
          placeholder="Enter username"
          value={username}
          onChange={e => setUsername(e.target.value)}
        />

        <label className="label">Password</label>
        <input
          className="input"
          type="password"
          placeholder="Enter password"
          value={password}
          onChange={e => setPassword(e.target.value)}
        />

        {tab === "register" && (
          <>
            <label className="label">Email</label>
            <input
              className="input"
              placeholder="Enter email"
              value={email}
              onChange={e => setEmail(e.target.value)}
            />
          </>
        )}

        <button
          onClick={tab === "login" ? handleLogin : handleRegister}
          disabled={loading}
          style={{
            marginTop: "30px",
            width: "100%",
            padding: "12px",
            borderRadius: "8px",
            border: "none",
            background: "#0B5ED7",
            color: "white",
            fontWeight: "600",
            fontSize: "16px",
            cursor: "pointer"
          }}>
          {loading ? "Please wait..." : tab === "login" ? "Login" : "Create Account"}
        </button>

      </div>
    </div>
  );
}
