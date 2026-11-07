import {
  AppstoreOutlined, AuditOutlined, BarChartOutlined, BarcodeOutlined, ContainerOutlined, DashboardOutlined, KeyOutlined,
  LogoutOutlined, OrderedListOutlined, ShopOutlined, TagsOutlined, TeamOutlined, UnorderedListOutlined, UploadOutlined, UserOutlined,
} from "@ant-design/icons";
import { Button, Dropdown, Grid, Layout, Menu, Segmented, Space, Typography } from "antd";
import type { MenuProps } from "antd";
import { useEffect, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { roleName } from "./roles";
import { useI18n } from "../i18n";

const { Sider, Header, Content } = Layout;

export type Section = "checking" | "stocktaking";
type Item = { key: string; icon: ReactNode; label: string };

/** Which main tab a path belongs to; shared pages (users, permissions, audit) return null. */
export function sectionOf(path: string): Section | null {
  if (path.startsWith("/stocktaking")) return "stocktaking";
  if (["/users", "/permissions", "/audit"].some((p) => path.startsWith(p))) return null;
  return "checking";
}

export function useSectionItems() {
  const { t } = useI18n();
  const { can } = useAuth();
  const keep = (xs: (Item | false)[]) => xs.filter(Boolean) as Item[];
  return {
    checking: keep([
      can("orders.view") && { key: "/dashboard", icon: <DashboardOutlined />, label: t("menu.dashboard") },
      can("orders.view") && { key: "/orders", icon: <OrderedListOutlined />, label: t("menu.orders") },
      (can("orders.import") || can("barcodes.manage")) && { key: "/imports", icon: <UploadOutlined />, label: t("menu.imports") },
      can("orders.view") && { key: "/barcodes", icon: <BarcodeOutlined />, label: t("menu.barcodes") },
      can("orders.view") && { key: "/reasons", icon: <TagsOutlined />, label: t("menu.reasons") },
      can("reports.view") && { key: "/reports", icon: <BarChartOutlined />, label: t("menu.reports") },
    ]),
    stocktaking: keep([
      can("stocktake.manage") && { key: "/stocktaking", icon: <ContainerOutlined />, label: t("menu.stocktakeList") },
      can("stocktake.manage") && { key: "/stocktaking/master", icon: <UnorderedListOutlined />, label: t("menu.master") },
      can("stocktake.manage") && { key: "/stocktaking/vendors", icon: <ShopOutlined />, label: t("menu.vendors") },
      can("stocktake.manage") && { key: "/stocktaking/reports", icon: <BarChartOutlined />, label: t("menu.stReports") },
    ]),
    system: keep([
      can("users.manage") && { key: "/users", icon: <TeamOutlined />, label: t("menu.users") },
      can("users.manage") && { key: "/permissions", icon: <KeyOutlined />, label: t("menu.permissions") },
      can("audit.view") && { key: "/audit", icon: <AuditOutlined />, label: t("menu.audit") },
    ]),
  };
}

const remembered = (): Section | null => {
  try { const v = localStorage.getItem("oc.section"); return v === "checking" || v === "stocktaking" ? v : null; } catch { return null; }
};

export default function AppLayout({ children }: { children: ReactNode }) {
  const { t, lang, setLang, calendar, setCalendar } = useI18n();
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const screens = Grid.useBreakpoint();
  const [collapsed, setCollapsed] = useState(false);
  const items = useSectionItems();
  const available = (["checking", "stocktaking"] as const).filter((s) => items[s].length > 0);

  // The main tab follows the page; shared pages keep the tab you came from.
  const fromPath = sectionOf(loc.pathname);
  const [section, setSection] = useState<Section>(fromPath ?? remembered() ?? available[0] ?? "checking");
  useEffect(() => { if (fromPath && fromPath !== section) setSection(fromPath); }, [fromPath, section]);
  useEffect(() => { try { localStorage.setItem("oc.section", section); } catch { /* private mode */ } }, [section]);

  const sectionItems = items[available.includes(section) ? section : available[0] ?? "checking"];
  const menuItems: MenuProps["items"] = [
    ...sectionItems,
    ...(items.system.length ? [{ type: "divider" as const }, { type: "group" as const, label: t("menu.system"), children: items.system }] : []),
  ];
  const allKeys = [...sectionItems, ...items.system].map((i) => i.key);
  const selected = allKeys.filter((k) => loc.pathname === k || loc.pathname.startsWith(k + "/"))
    .sort((a, b) => b.length - a.length)[0]
    // /stocktaking/123 (a stocktake) belongs to the stocktakes list.
    ?? (loc.pathname.startsWith("/stocktaking") ? "/stocktaking" : undefined);
  const exact = allKeys.find((k) => k === loc.pathname);

  const switchTo = (s: Section) => { setSection(s); nav(items[s][0]?.key ?? "/"); };
  const narrow = collapsed || !screens.lg;

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider collapsible collapsed={narrow} onCollapse={setCollapsed} breakpoint="lg" width={220}>
        <div className="oc-logo">
          <img src="/favicon.svg" alt="" />
          {!narrow && <span>{t("app.short")}</span>}
        </div>
        <Menu theme="dark" mode="inline" selectedKeys={exact ? [exact] : selected ? [selected] : []} items={menuItems} onClick={(e) => nav(e.key)} />
      </Sider>
      <Layout>
        <Header className="oc-header">
          <Space size="middle" align="center">
            {available.length > 1 ? (
              <Segmented className="oc-main-tabs" value={section} onChange={(v) => switchTo(v as Section)}
                options={available.map((s) => ({
                  value: s,
                  label: <span className="oc-main-tab">{s === "checking" ? <AppstoreOutlined /> : <ContainerOutlined />} {t(`menu.${s}Section`)}</span>,
                }))} />
            ) : (
              <Typography.Text strong style={{ fontSize: 16 }}>{t(`menu.${available[0] ?? "checking"}Section`)}</Typography.Text>
            )}
          </Space>
          <Space size="middle" wrap>
            <Segmented size="small" value={lang} onChange={(v) => setLang(v as "fa" | "en")}
              options={[{ label: "فارسی", value: "fa" }, { label: "EN", value: "en" }]} />
            <Segmented size="small" value={calendar} onChange={(v) => setCalendar(v as "jalali" | "gregorian")}
              options={[{ label: t("common.jalali"), value: "jalali" }, { label: t("common.gregorian"), value: "gregorian" }]} />
            <Dropdown menu={{ items: [{ key: "logout", icon: <LogoutOutlined />, label: t("common.logout"), onClick: logout }] }}>
              <Button icon={<UserOutlined />}>
                {user?.full_name || user?.username} · {(user?.role_names ?? []).map((r) => roleName(r, r.code, lang)).join("، ")}
              </Button>
            </Dropdown>
          </Space>
        </Header>
        <Content style={{ padding: 24 }}>{children}</Content>
      </Layout>
    </Layout>
  );
}
