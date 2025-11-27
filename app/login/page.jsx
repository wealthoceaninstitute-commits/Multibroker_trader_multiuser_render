"use client";

import { useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";

export default function LoginPage() {
  const [activeTab, setActiveTab] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // If already logged in, go directly to trader page
  useEffect(() => {
    if (typeof window === "undefined") return;
    const token = localStorage.getItem("woi_token");
    if (token) {
      window.location.href = "/trader";
    }
  }, []);

  function resetMessages() {
    setErrorMsg(null);
    setSuccessMsg(null);
  }

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    resetMessages();

    if (!username || !password) {
      setErrorMsg("Please enter both username and password.");
      return;
    }

    try {
      setLoading(true);
      const resp = await fetch(`${API_BASE}/users/login`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ username, password }),
      });

      const data = await resp.json().catch(() => ({}));

      if (!resp.ok) {
        setErrorMsg(
          typeof data?.detail === "string"
            ? data.detail
            : "Login failed. Please check your credentials."
        );
        return;
      }

      const token = data.authToken || data.token;
      if (!token) {
        setErrorMsg("Login succeeded but token missing in response.");
        return;
      }

      if (typeof window !== "undefined") {
        localStorage.setItem("woi_token", token);
        localStorage.setItem("woi_username", data.username || username);
      }

      setSuccessMsg("Login successful. Redirecting…");
      // Redirect to trader dashboard
      window.location.href = "/trader";
    } catch (err) {
      console.error("Login error:", err);
      setErrorMsg("Network error while logging in.");
    } finally {
      setLoading(false);
    }
  }

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault();
    resetMessages();

    if (!username || !password) {
      setErrorMsg("Username and password are required.");
      return;
    }

    try {
      setLoading(true);
      const resp = await fetch(`${API_BASE}/users/register`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ username, password }),
      });

      const data = await resp.json().catch(() => ({}));

      if (!resp.ok) {
        setErrorMsg(
          typeof data?.detail === "string"
            ? data.detail
            : "User creation failed. Try a different username."
        );
        return;
      }

      const token = data.authToken || data.token;
      if (!token) {
        setErrorMsg("User created but token missing in response.");
        return;
      }

      if (typeof window !== "undefined") {
        localStorage.setItem("woi_token", token);
        localStorage.setItem("woi_username", data.username || username);
      }

      setSuccessMsg("User created successfully. Redirecting…");
      window.location.href = "/trader";
    } catch (err) {
      console.error("Register error:", err);
      setErrorMsg("Network error while creating user.");
    } finally {
      setLoading(false);
    }
  }

  const isLogin = activeTab === "login";

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="w-full max-w-xl bg-white shadow-md rounded-lg p-8">
        <h1 className="text-2xl font-semibold text-center mb-2">
          Wealth Ocean – Login
        </h1>
        <p className="text-center text-gray-600 mb-6">
          Multi-broker, multi-user trading panel
        </p>

        {/* Tabs */}
        <div className="flex border-b mb-6">
          <button
            className={`flex-1 py-2 text-center ${
              isLogin
                ? "border-b-2 border-blue-600 font-semibold"
                : "text-gray-500"
            }`}
            onClick={() => {
              setActiveTab("login");
              resetMessages();
            }}
          >
            Login
          </button>
          <button
            className={`flex-1 py-2 text-center ${
              !isLogin
                ? "border-b-2 border-blue-600 font-semibold"
                : "text-gray-500"
            }`}
            onClick={() => {
              setActiveTab("register");
              resetMessages();
            }}
          >
            Create New User
          </button>
        </div>

        {/* Alerts */}
        {errorMsg && (
          <div className="mb-4 rounded border border-red-300 bg-red-50 px-4 py-2 text-red-700 text-sm">
            {errorMsg}
          </div>
        )}
        {successMsg && (
          <div className="mb-4 rounded border border-green-300 bg-green-50 px-4 py-2 text-green-700 text-sm">
            {successMsg}
          </div>
        )}

        {/* Forms */}
        {isLogin ? (
          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1">
                User ID / Username
              </label>
              <input
                type="text"
                className="w-full border rounded px-3 py-2 text-sm"
                placeholder="Enter your user id"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={loading}
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">Password</label>
              <input
                type="password"
                className="w-full border rounded px-3 py-2 text-sm"
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={loading}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-blue-600 text-white font-semibold py-2 rounded hover:bg-blue-700 disabled:opacity-60"
            >
              {loading ? "Logging in..." : "Login"}
            </button>
          </form>
        ) : (
          <form onSubmit={handleRegister} className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1">
                User ID / Username
              </label>
              <input
                type="text"
                className="w-full border rounded px-3 py-2 text-sm"
                placeholder="Choose a user id"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={loading}
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">
                Email (optional)
              </label>
              <input
                type="email"
                className="w-full border rounded px-3 py-2 text-sm"
                placeholder="Enter your email (optional)"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={loading}
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">Password</label>
              <input
                type="password"
                className="w-full border rounded px-3 py-2 text-sm"
                placeholder="Choose a password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={loading}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-green-600 text-white font-semibold py-2 rounded hover:bg-green-700 disabled:opacity-60"
            >
              {loading ? "Creating..." : "Create User"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
