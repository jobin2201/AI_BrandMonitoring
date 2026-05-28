import React from "react";
import "../styles/global.css";

export default function DashboardLayout({ sidebar, rightPanel, children }) {
  return (
    <div className="dashboard-layout">
      <aside className="sidebar">{sidebar}</aside>
      <main className="main-content">{children}</main>
      <aside className="right-panel">{rightPanel}</aside>
    </div>
  );
}
