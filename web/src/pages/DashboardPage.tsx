import { ReloadOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Button, Card, Col, List, Row, Statistic, Table, Tag, Typography } from "antd";
import { useNavigate } from "react-router-dom";
import { get, type Page } from "../api/client";
import type { OrderListItem, Summary } from "../api/types";
import { useCheckers } from "../components/AssignModal";
import { Ltr, OrderProgress, StatusTag } from "../components/common";
import { useI18n } from "../i18n";

const CARDS: { key: keyof Summary; color: string; link: string }[] = [
  { key: "waiting_assignment", color: "#64748b", link: "/orders?unassigned=true&status=pending_assignment,assigned,in_progress" },
  { key: "assigned_not_started", color: "#2563eb", link: "/orders?status=assigned" },
  { key: "in_progress", color: "#0f766e", link: "/orders?status=in_progress" },
  { key: "open_issues", color: "#dc2626", link: "/orders?open_issues=true&status=pending_assignment,assigned,in_progress" },
  { key: "completed_today", color: "#16a34a", link: "/orders?status=completed" },
  { key: "completed_with_issues_today", color: "#ea580c", link: "/orders?status=completed&has_issues=true" },
  { key: "boxes_scanned_today", color: "#7c3aed", link: "" },
];

export default function DashboardPage() {
  const { t, num, of, dateTime } = useI18n();
  const nav = useNavigate();
  const summary = useQuery({ queryKey: ["summary"], queryFn: () => get<Summary>("orders/summary/"), refetchInterval: 10_000 });
  const active = useQuery({
    queryKey: ["orders", "active-board"],
    queryFn: () => get<Page<OrderListItem>>("orders/?status=in_progress,assigned&limit=100"),
    refetchInterval: 10_000,
  });
  const checkers = useCheckers();
  const now = summary.data ? new Date(summary.data.server_time).getTime() : Date.now();

  return (
    <>
      <div className="oc-page-header">
        <h2>{t("menu.dashboard")}</h2>
        <span>
          <Typography.Text type="secondary" style={{ marginInlineEnd: 8 }}>{t("dashboard.autoRefresh")}</Typography.Text>
          <Button icon={<ReloadOutlined />} onClick={() => { summary.refetch(); active.refetch(); checkers.refetch(); }} />
        </span>
      </div>

      <Row gutter={[12, 12]}>
        {CARDS.map((c) => (
          <Col key={c.key} flex="1 1 170px">
            <Card size="small" className={c.link ? "oc-stat" : undefined} onClick={() => c.link && nav(c.link)} style={{ borderTop: `3px solid ${c.color}` }}>
              <Statistic title={t(`dashboard.${c.key}`)} value={summary.data ? num(summary.data[c.key] as number) : "…"}
                valueStyle={{ color: c.color, fontWeight: 700 }} />
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} xl={18}>
          <Card title={t("dashboard.activeOrders")} size="small">
            <Table<OrderListItem>
              rowKey="id" size="small" loading={active.isLoading} dataSource={active.data?.results ?? []}
              pagination={false} scroll={{ x: 800 }}
              onRow={(r) => ({ onClick: () => nav(`/orders/${r.id}`), style: { cursor: "pointer" } })}
              rowClassName={(r) => (r.open_issues ? "oc-row-issue" : "")}
              columns={[
                { title: t("order.reference"), dataIndex: "reference_id", render: (v) => <Ltr>{v}</Ltr> },
                { title: t("order.customer"), dataIndex: "customer", ellipsis: true },
                { title: t("order.checker"), render: (_, r) => r.checker?.name ?? <Tag>{t("order.unassigned")}</Tag> },
                { title: t("common.status"), dataIndex: "status", render: (s) => <StatusTag status={s} /> },
                { title: t("order.progress"), render: (_, r) => <OrderProgress done={r.lines_done} total={r.lines_total} issues={r.open_issues} /> },
                { title: t("order.boxes"), render: (_, r) => of(r.boxes_scanned, r.boxes_ordered) },
                { title: t("order.openIssues"), dataIndex: "open_issues", render: (v) => (v ? <Tag color="red">{num(v)}</Tag> : num(0)) },
                { title: t("order.started"), dataIndex: "first_scan_at", render: (v) => dateTime(v) },
                {
                  title: t("order.duration"),
                  render: (_, r) => (r.first_scan_at ? <ElapsedLabel seconds={(now - new Date(r.first_scan_at).getTime()) / 1000} /> : t("common.none")),
                },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} xl={6}>
          <Card title={t("roles.checker")} size="small">
            <List
              loading={checkers.isLoading}
              dataSource={checkers.data ?? []}
              locale={{ emptyText: t("common.noData") }}
              renderItem={(c) => (
                <List.Item extra={<Tag color={c.active_orders ? "processing" : "default"}>{num(c.active_orders)}</Tag>}>
                  {c.name}
                </List.Item>
              )}
            />
          </Card>
        </Col>
      </Row>
    </>
  );
}

function ElapsedLabel({ seconds }: { seconds: number }) {
  const { duration } = useI18n();
  return <span>{duration(Math.max(0, seconds))}</span>;
}
