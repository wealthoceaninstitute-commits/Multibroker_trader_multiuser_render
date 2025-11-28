"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

const API = process.env.NEXT_PUBLIC_API_URL || "";

export default function Home() {
  const router = useRouter();

  const [tab, setTab] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState("");

  const handleLogin = async () => {
    setMsg("");

    try {
      const res = await fetch(`${API}/users/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: username.trim(),
          password: password.trim(),
        }),
      });

      const data = await res.json();

      if (!res.ok || !data.success) {
        setMsg(data.detail || "Login failed");
        return;
      }

      // Store login (simple)
      localStorage.setItem("woi_user", username);

      // ✅ Redirect to trader page
      router.replace("/trader");
    } catch (err) {
      console.error(err);
      setMsg("Server not reachable");
    }
  };

  const handleCreate = async () => {
    setMsg("");

    try {
      const res = await fetch(`${API}/users/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: username.trim(),
          password: password.trim(),
        }),
      });

      const data = await res.json();

      if (!res.ok || !data.success) {
        setMsg(data.detail || "User creation failed");
        return;
      }

      setMsg("✅ User created successfully. Now login.");
      setTab("login");
      setPassword("");
    } catch (err) {
      console.error(err);
      setMsg("Server not reachable");
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "Arial",
      }}
    >
      <div style={{ width: 400, padding: 30, border: "1px solid #ccc", borderRadius: 8 }}>
        <h2 style={{ textAlign: "center", marginBottom: 5 }}>
          Wealth Ocean – Login
        </h2>

        <p style={{ textAlign: "center", marginBottom: 20 }}>
          Multi-broker, multi-user trading panel
        </p>

        {msg && (
          <div
            style={{
              background: "#ffe0e0",
              padding: 10,
              marginBottom: 15,
              borderRadius: 5,
              textAlign: "center",
            }}
          >
            {msg}
          </div>
        )}

        {/* Tabs */}
        <div style={{ display: "flex", marginBottom: 20 }}>
          <button
            onClick={() => setTab("login")}
            style={{
              flex: 1,
              padding: 10,
              background: tab === "login" ? "#000" : "#ddd",
              color: tab === "login" ? "white" : "black",
              border: "1px solid #000",
              cursor: "pointer",
            }}
          >
            Login
          </button>

          <button
            onClick={() => setTab("create")}
            style={{
              flex: 1,
              padding: 10,
              background: tab === "create" ? "#000" : "#ddd",
              color: tab === "create" ? "white" : "black",
              border: "1px solid #000",
              cursor: "pointer",
            }}
          >
            Create User
          </button>
        </div>

        <label>User ID</label>
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          style={{ width: "100%", padding: 8, marginBottom: 10 }}
        />

        <label>Password</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={{ width: "100%", padding: 8, marginBottom: 20 }}
        />

        {tab === "login" ? (
          <button
            onClick={handleLogin}
            style={{
              width: "100%",
              padding: 12,
              background: "#2563eb",
              color: "white",
              border: "none",
              cursor: "pointer",
              fontSize: 16,
            }}
          >
            Login
          </button>
        ) : (
          <button
            onClick={handleCreate}
            style={{
              width: "100%",
              padding: 12,
              background: "#15803d",
              color: "white",
              border: "none",
              cursor: "pointer",
              fontSize: 16,
            }}
          >
            Create User
          </button>
        )}
      </div>
    </div>
  );
}
