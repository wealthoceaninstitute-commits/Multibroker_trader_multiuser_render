"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  // ✅ Backend base URL
  const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "https://multibrokertradermultiuser-production-f735.up.railway.app";

  const handleLogin = async (e) => {
    e.preventDefault();

    if (!email || !password) {
      alert("Please enter Email and Password");
      return;
    }

    setLoading(true);

    try {
      const res = await fetch(`${API_BASE}/users/login`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          email: email.trim().toLowerCase(),
          password: password
        })
      });

      const data = await res.json();

      if (!res.ok) {
        alert(data.detail || "Login failed");
        setLoading(false);
        return;
      }

      // ✅ Save token
      localStorage.setItem("auth_token", data.token);
      localStorage.setItem("username", data.username);

      alert("✅ Login Successful");

      // ✅ Go to trading page
      router.push("/");

    } catch (err) {
      console.error(err);
      alert("Server not reachable");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "radial-gradient(circle at top, #162447 0%, #0f172a 80%)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center"
      }}
    >
      <div
        style={{
          background: "white",
          padding: "40px",
          borderRadius: "14px",
          width: "400px",
          boxShadow: "0 25px 50px rgba(0,0,0,0.25)",
          textAlign: "center"
        }}
      >
        <h1 style={{ marginBottom: "30px" }}>Login</h1>

        <form onSubmit={handleLogin}>
          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            style={inputStyle}
          />

          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={inputStyle}
          />

          <button
            type="submit"
            disabled={loading}
            style={{
              width: "100%",
              padding: "12px",
              background: "#1e40af",
              color: "white",
              border: "none",
              borderRadius: "8px",
              fontWeight: "600",
              cursor: "pointer",
              marginTop: "10px"
            }}
          >
            {loading ? "Logging in..." : "Login"}
          </button>
        </form>

        <p style={{ marginTop: "20px", fontSize: "14px" }}>
          Don’t have an account?{" "}
          <span
            onClick={() => router.push("/signup")}
            style={{ color: "#1e40af", cursor: "pointer" }}
          >
            Create new account
          </span>
        </p>
      </div>
    </div>
  );
}

const inputStyle = {
  width: "100%",
  padding: "12px",
  marginBottom: "15px",
  border: "1px solid #d1d5db",
  borderRadius: "8px",
  fontSize: "15px"
};
