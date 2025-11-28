"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export default function TraderPage() {
  const router = useRouter();
  const [user, setUser] = useState(null);

  useEffect(() => {
    const loggedIn = localStorage.getItem("auth");
    const u = localStorage.getItem("user");

    if (!loggedIn || !u) {
      router.replace("/login");
    } else {
      setUser(u);
    }
  }, []);

  const logout = () => {
    localStorage.clear();
    router.replace("/login");
  };

  if (!user) return null;

  return (
    <div style={{ padding: "20px" }}>
      <h1>Wealth Ocean – Multi-Broker Trader</h1>
      <p>Logged in as <strong>{user}</strong></p>

      <button onClick={logout}>Logout</button>

      <hr style={{ margin: "20px 0" }} />

      {/* YOUR EXISTING COMPONENTS CAN BE ADDED BELOW */}
      <h3>Trade | Orders | Positions | Holdings | Summary | Clients | Copy Trading</h3>

      <div style={{ marginTop: "20px" }}>
        Place your TradeForm.jsx here next ✅
      </div>
    </div>
  );
}
