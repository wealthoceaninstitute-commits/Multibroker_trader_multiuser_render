"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function SignupPage() {
  const router = useRouter();

  const [form, setForm] = useState({
    username: "",
    password: "",
    confirm: "",
  });

  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const handleChange = (e) => {
    setForm({ ...form, [e.target.name]: e.target.value });
  };

  const handleSignup = async (e) => {
    e.preventDefault();

    if (!form.username || !form.password || !form.confirm) {
      setMessage("All fields are required");
      return;
    }

    if (form.password !== form.confirm) {
      setMessage("Passwords do not match");
      return;
    }

    try {
      setLoading(true);
      setMessage("");

      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_BASE}/create-user`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            username: form.username.trim(),
            password: form.password,
          }),
        }
      );

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error || "Signup failed");
      }

      setMessage("✅ User created successfully! Redirecting to login…");

      setTimeout(() => {
        router.push("/login");
      }, 1500);
    } catch (err) {
      setMessage(`❌ ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        background: "#0f172a",
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      <form
        onSubmit={handleSignup}
        style={{
          width: "100%",
          maxWidth: "420px",
          background: "#111827",
          padding: "30px",
          borderRadius: "12px",
          boxShadow: "0 0 20px rgba(0,0,0,0.5)",
          border: "1px solid #1e293b",
        }}
      >
        <h2
          style={{
            color: "#22c55e",
            textAlign: "center",
            marginBottom: "20px",
            fontSize: "24px",
            fontWeight: "600",
          }}
        >
          Create Your Account
        </h2>

        {message && (
          <div
            style={{
              marginBottom: "15px",
              padding: "10px",
              background: "#020617",
              border: "1px solid #1e293b",
              borderRadius: "6px",
              color: message.startsWith("✅") ? "#22c55e" : "#ef4444",
              fontSize: "14px",
            }}
          >
            {message}
          </div>
        )}

        <label style={labelStyle}>Username</label>
        <input
          type="text"
          name="username"
          value={form.username}
          onChange={handleChange}
          placeholder="Enter username"
          style={inputStyle}
        />

        <label style={labelStyle}>Password</label>
        <input
          type="password"
          name="password"
          value={form.password}
          onChange={handleChange}
          placeholder="Enter password"
          style={inputStyle}
        />

        <label style={labelStyle}>Confirm Password</label>
        <input
          type="password"
          name="confirm"
          value={form.confirm}
          onChange={handleChange}
          placeholder="Confirm password"
          style={inputStyle}
        />

        <button
          disabled={loading}
          style={{
            width: "100%",
            marginTop: "10px",
            padding: "12px",
            borderRadius: "8px",
            border: "none",
            background: "#22c55e",
            color: "#020617",
            fontSize: "15px",
            fontWeight: "600",
            cursor: "pointer",
            opacity: loading ? 0.7 : 1,
          }}
        >
          {loading ? "Creating..." : "Create Account"}
        </button>

        <p
          onClick={() => router.push("/login")}
          style={{
            marginTop: "16px",
            textAlign: "center",
            color: "#94a3b8",
            fontSize: "14px",
            cursor: "pointer",
          }}
        >
          Already have account? Login →
        </p>
      </form>
    </div>
  );
}

/* styles */
const inputStyle = {
  width: "100%",
  padding: "10px",
  marginBottom: "14px",
  borderRadius: "6px",
  border: "1px solid #334155",
  background: "#020617",
  color: "#e2e8f0",
  fontSize: "14px",
};

const labelStyle = {
  fontSize: "13px",
  marginBottom: "4px",
  display: "block",
  color: "#94a3b8",
};
