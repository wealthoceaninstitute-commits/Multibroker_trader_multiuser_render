"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading,setLoading] = useState(false);

  const router = useRouter();

  async function login() {
    try {
      setLoading(true);

      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_BASE}/users/login`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password })
        }
      );

      const data = await res.json();

      if (!res.ok) {
        alert(data.detail || "Login failed");
        setLoading(false);
        return;
      }

      // Save token
      localStorage.setItem("auth_token", data.token);
      localStorage.setItem("username", data.username);

      alert("✅ Login Successful");

      // LAND ON TRADE PAGE (NEXT STAGE)
      router.push("/trade");

    } catch (err) {
      alert("Server not reachable");
      console.error(err);
    }
    finally{
      setLoading(false);
    }
  }

  return (
    <div style={{
      display: "flex",
      justifyContent: "center",
      alignItems: "center",
      height: "100vh",
      background: "linear-gradient(135deg, #0f172a, #1e3a8a)"
    }}>

      <div style={{
        width: 350,
        background: "white",
        padding: 30,
        borderRadius: 12,
        boxShadow: "0 20px 40px rgba(0,0,0,0.3)",
        textAlign: "center"
      }}>

        <h2 style={{ marginBottom: 20 }}>Login</h2>

        <input
          style={inputStyle}
          placeholder="Email"
          type="email"
          onChange={e => setEmail(e.target.value)}
        />

        <input
          style={inputStyle}
          placeholder="Password"
          type="password"
          onChange={e => setPassword(e.target.value)}
        />

        <button
          style={{
            ...btnStyle,
            background: loading ? "#64748b" : "#1e40af"
          }}
          onClick={login}
          disabled={loading}
        >
          {loading ? "Logging in..." : "Login"}
        </button>

        <p
          style={{ marginTop: 15, cursor: "pointer", color: "#1e40af" }}
          onClick={() => router.push("/signup")}
        >
          Don&apos;t have account? Create new account
        </p>

      </div>
    </div>
  );
}


const inputStyle = {
  width: "100%",
  padding: "12px",
  marginBottom: 15,
  borderRadius: 8,
  border: "1px solid #ccc",
  outline: "none",
  fontSize: 14
}

const btnStyle = {
  width: "100%",
  padding: "12px",
  background: "#1e40af",
  color: "white",
  border: "none",
  borderRadius: 8,
  cursor: "pointer",
  fontWeight: "bold"
}
