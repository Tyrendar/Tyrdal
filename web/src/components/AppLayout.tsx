import {
  AuditOutlined, BarChartOutlined, BarcodeOutlined, DashboardOutlined, KeyOutlined, LogoutOutlined, OrderedListOutlined,
  TagsOutlined, TeamOutlined, UploadOutlined, UserOutlined,
} from "@ant-design/icons";
import { Button, Dropdown, Grid, Layout, Menu, Segmented, Space, Typography } from "antd";
import { useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";

const { Sider, Header, Content } = Layout;

export default function AppLayout({ children }: { children: ReactNode }) {
  const { t, lang, setLang, calendar, setCalendar } = useI18n();
  const { user, can, logout } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const screens = Grid.useBreakpoint();
  const [collapsed, setCollapsed] = useState(false);

  const items = [
    can("orders.view") && { key: "/dashboard", icon: <DashboardOutlined />, label: t("menu.dashboard") },
    can("orders.view") && { key: "/orders", icon: <OrderedListOutlined />, label: t("menu.orders") },
    can("reports.view") && { key: "/reports", icon: <BarChartOutlined />, label: t("menu.reports") },
    (can("orders.import") || can("barcodes.manage")) && { key: "/imports", icon: <UploadOutlined />, label: t("menu.imports") },
    { key: "/barcodes", icon: <BarcodeOutlined />, label: t("menu.barcodes") },
    { key: "/reasons", icon: <TagsOutlined />, label: t("menu.reasons") },
    can("users.manage") && { key: "/users", icon: <TeamOutlined />, label: t("menu.users") },
    can("users.manage") && { key: "/permissions", icon: <KeyOutlined />, label: t("menu.permissions") },
    can("audit.view") && { key: "/audit", icon: <AuditOutlined />, label: t("menu.audit") },
  ].filter(Boolean) as { key: string; icon: ReactNode; label: string }[];

  const selected = items.map((i) => i.key).filter((k) => loc.pathname.startsWith(k)).sort((a, b) => b.length - a.length)[0];

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider collapsible collapsed={collapsed || !screens.lg} onCollapse={setCollapsed} breakpoint="lg" width={220}>
        <div className="oc-logo">
          <img src="/favicon.svg" alt="" />
          {!(collapsed || !screens.lg) && <span>{t("app.short")}</span>}
        </div>
        <Menu theme="dark" mode="inline" selectedKeys={selected ? [selected] : []} items={items} onClick={(e) => nav(e.key)} />
      </Sider>
      <Layout>
        <Header style={{ background: "#fff", paddingInline: 16, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, borderBottom: "1px solid #e5e7eb" }}>
          <Typography.Text strong style={{ fontSize: 16 }}>{t("app.title")}</Typography.Text>
          <Space size="middle" wrap>
            <Segmented size="small" value={lang} onChange={(v) => setLang(v as "fa" | "en")}
              options={[{ label: "فارسی", value: "fa" }, { label: "EN", value: "en" }]} />
            <Segmented size="small" value={calendar} onChange={(v) => setCalendar(v as "jalali" | "gregorian")}
              options={[{ label: t("common.jalali"), value: "jalali" }, { label: t("common.gregorian"), value: "gregorian" }]} />
            <Dropdown menu={{ items: [{ key: "logout", icon: <LogoutOutlined />, label: t("common.logout"), onClick: logout }] }}>
              <Button icon={<UserOutlined />}>{user?.full_name || user?.username} · {t(`roles.${user?.role}`)}</Button>
            </Dropdown>
          </Space>
        </Header>
        <Content style={{ padding: 24 }}>{children}</Content>
      </Layout>
    </Layout>
  );
}
