"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { clearCurrentUser, getCurrentUser } from "../../src/lib/userSession";
import Tabs from "../../src/components/Tabs";

export default function TraderPage() {
  const router = useRouter();
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(true); // ✅ prevents flicker loop

  useEffect(() => {
    // Wait for client side before checking
    if (typeof window === "undefined") return;

    const username = getCurrentUser();
    const token = localStorage.getItem("token");

    if (!username || !token) {
      router.replace("/login");
    } else {
      setUser(username);
    }

    setChecking(false);
  }, [router]);

  const handleLogout = () => {
    clearCurrentUser();
    localStorage.removeItem("token");
    localStorage.removeItem("username");
    router.push("/login");
  };

  if (checking) {
    return (
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#f9fafb",
        }}
      >
        <p style={{ color: "#64748b" }}>Loading...</p>
      </div>
    );
  }

  if (!user) return null; // nothing till verified

  return (
    <div style={{ padding: "20px" }}>
      <h1 style={{ textAlign: "center", marginBottom: "10px" }}>
        Wealth Ocean – Multi-Broker Trader
      </h1>
      <div style={{ textAlign: "right", marginBottom: "10px" }}>
        <span style={{ marginRight: "8px", color: "#475569" }}>
          Logged in as <b>{user}</b>
        </span>
        <button
          onClick={handleLogout}
          style={{
            border: "1px solid #cbd5e1",
            padding: "4px 8px",
            borderRadius: "6px",
            cursor: "pointer",
            background: "#fff",
          }}
        >
          Logout
        </button>
      </div>

      <Tabs />
    </div>
  );
}
