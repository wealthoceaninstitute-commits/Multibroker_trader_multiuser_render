"use client";

import { useState } from "react";

// Import your existing components
import TradeForm from "@/components/TradeForm";
import Orders from "@/components/Orders";
import Positions from "@/components/Positions";
import Holdings from "@/components/Holdings";
import Summary from "@/components/Summary";
import Clients from "@/components/Clients";
import CopyTrading from "@/components/CopyTrading";

export default function TradePage() {
  const [activeTab, setActiveTab] = useState("trade");

  const tabStyle = (tab) => ({
    padding: "8px 16px",
    cursor: "pointer",
    borderBottom: activeTab === tab ? "2px solid blue" : "1px solid #ddd",
    color: activeTab === tab ? "blue" : "#333",
    fontWeight: activeTab === tab ? "600" : "400",
  });

  return (
    <div style={{ padding: "20px" }}>

      {/* TOP NAV TABS */}
      <div
        style={{
          display: "flex",
          gap: "15px",
          borderBottom: "1px solid #ccc",
          marginBottom: "20px",
          flexWrap: "wrap",
        }}
      >
        <span onClick={() => setActiveTab("trade")} style={tabStyle("trade")}>
          Trade
        </span>

        <span onClick={() => setActiveTab("orders")} style={tabStyle("orders")}>
          Orders
        </span>

        <span onClick={() => setActiveTab("positions")} style={tabStyle("positions")}>
          Positions
        </span>

        <span onClick={() => setActiveTab("holdings")} style={tabStyle("holdings")}>
          Holdings
        </span>

        <span onClick={() => setActiveTab("summary")} style={tabStyle("summary")}>
          Summary
        </span>

        <span onClick={() => setActiveTab("clients")} style={tabStyle("clients")}>
          Clients
        </span>

        <span onClick={() => setActiveTab("copy")} style={tabStyle("copy")}>
          Copy Trading
        </span>
      </div>


      {/* CONTENT AREA */}
      <div>
        {activeTab === "trade" && <TradeForm />}
        {activeTab === "orders" && <Orders />}
        {activeTab === "positions" && <Positions />}
        {activeTab === "holdings" && <Holdings />}
        {activeTab === "summary" && <Summary />}
        {activeTab === "clients" && <Clients />}
        {activeTab === "copy" && <CopyTrading />}
      </div>

    </div>
  );
}
