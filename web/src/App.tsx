import { useQuery } from "@tanstack/react-query";
import { Spin } from "antd";
import { Navigate, Route, Routes } from "react-router-dom";
import { get } from "./api/client";
import type { Reason } from "./api/types";
import { useAuth } from "./auth";
import { reasonNames } from "./components/common";
import AppLayout from "./components/AppLayout";
import AuditPage from "./pages/AuditPage";
import BarcodesPage from "./pages/BarcodesPage";
import DashboardPage from "./pages/DashboardPage";
import ImportDetailPage from "./pages/ImportDetailPage";
import ImportsPage from "./pages/ImportsPage";
import LoginPage from "./pages/LoginPage";
import OrderDetailPage from "./pages/OrderDetailPage";
import OrdersPage from "./pages/OrdersPage";
import PermissionsPage from "./pages/PermissionsPage";
import ReasonsPage from "./pages/ReasonsPage";
import ReportsPage from "./pages/ReportsPage";
import UsersPage from "./pages/UsersPage";

function ReasonsCache() {
  // Keeps reason names available to discrepancy tags everywhere.
  useQuery({
    queryKey: ["reasons", "all"],
    queryFn: async () => {
      const list = await get<Reason[]>("reasons/?limit=500").then((r) => (Array.isArray(r) ? r : (r as unknown as { results: Reason[] }).results));
      for (const r of list) reasonNames[r.code] = { fa: r.name_fa, en: r.name_en };
      return list;
    },
    staleTime: 60_000,
  });
  return null;
}

export default function App() {
  const { user, ready, can } = useAuth();
  if (!ready) return <div style={{ display: "grid", placeItems: "center", height: "100%" }}><Spin size="large" /></div>;
  if (!user) return <LoginPage />;

  const home = can("orders.view") ? "/dashboard" : can("users.manage") ? "/users" : "/barcodes";
  return (
    <AppLayout>
      <ReasonsCache />
      <Routes>
        <Route path="/" element={<Navigate to={home} replace />} />
        {can("orders.view") && <Route path="/dashboard" element={<DashboardPage />} />}
        {can("orders.view") && <Route path="/orders" element={<OrdersPage />} />}
        {can("orders.view") && <Route path="/orders/:id" element={<OrderDetailPage />} />}
        {(can("orders.import") || can("barcodes.manage")) && <Route path="/imports" element={<ImportsPage />} />}
        {(can("orders.import") || can("barcodes.manage")) && <Route path="/imports/:id" element={<ImportDetailPage />} />}
        {can("reports.view") && <Route path="/reports" element={<ReportsPage />} />}
        <Route path="/barcodes" element={<BarcodesPage />} />
        <Route path="/reasons" element={<ReasonsPage />} />
        {can("users.manage") && <Route path="/users" element={<UsersPage />} />}
        {can("users.manage") && <Route path="/permissions" element={<PermissionsPage />} />}
        {can("audit.view") && <Route path="/audit" element={<AuditPage />} />}
        <Route path="*" element={<Navigate to={home} replace />} />
      </Routes>
    </AppLayout>
  );
}
