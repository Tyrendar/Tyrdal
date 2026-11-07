import { ReloadOutlined, ThunderboltOutlined, UserAddOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Button, Checkbox, Input, Select, Table, Tag } from "antd";
import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { get, qs, type Page } from "../api/client";
import type { OrderListItem, OrderStatus } from "../api/types";
import { useAuth } from "../auth";
import AssignModal, { useCheckers } from "../components/AssignModal";
import AutoAssignModal from "../components/AutoAssignModal";
import { DateRange } from "../components/DateRange";
import { Ltr, OrderProgress, StatusTag } from "../components/common";
import { useI18n } from "../i18n";

const STATUSES: OrderStatus[] = ["pending_assignment", "assigned", "in_progress", "completed", "cancelled"];
const PAGE = 50;

export default function OrdersPage() {
  const { t, num, of, dateTime, duration } = useI18n();
  const { can } = useAuth();
  const nav = useNavigate();
  const [sp, setSp] = useSearchParams();
  const [selected, setSelected] = useState<number[]>([]);
  const [autoOpen, setAutoOpen] = useState(false);
  const [assignOpen, setAssignOpen] = useState(false);
  const checkers = useCheckers();

  const filters = {
    status: sp.get("status") ?? "",
    checker: sp.get("checker") ?? "",
    q: sp.get("q") ?? "",
    from: sp.get("from") ?? "",
    to: sp.get("to") ?? "",
    unassigned: sp.get("unassigned") ?? "",
    has_issues: sp.get("has_issues") ?? "",
    open_issues: sp.get("open_issues") ?? "",
  };
  const page = Number(sp.get("page") ?? 1);
  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(sp);
    for (const [k, v] of Object.entries(patch)) if (v) next.set(k, v); else next.delete(k);
    if (!("page" in patch)) next.delete("page");
    setSp(next, { replace: true });
  };

  const query = useMemo(() => qs({ ...filters, limit: PAGE, offset: (page - 1) * PAGE }), [sp]); // eslint-disable-line react-hooks/exhaustive-deps
  const orders = useQuery({ queryKey: ["orders", query], queryFn: () => get<Page<OrderListItem>>(`orders/${query}`), refetchInterval: 15_000 });

  const assignable = (o: OrderListItem) => !o.checker && (o.status === "pending_assignment" || o.status === "assigned" || o.status === "in_progress");

  return (
    <>
      <div className="oc-page-header">
        <h2>{t("menu.orders")}</h2>
        <span style={{ display: "flex", gap: 8 }}>
          {can("orders.assign") && (
            <Button icon={<ThunderboltOutlined />} onClick={() => setAutoOpen(true)}>
              {t("auto.button")} {selected.length ? `(${num(selected.length)})` : ""}
            </Button>
          )}
          {can("orders.assign") && (
            <Button type="primary" icon={<UserAddOutlined />} disabled={!selected.length} onClick={() => setAssignOpen(true)}>
              {t("order.bulkAssign")} {selected.length ? `(${num(selected.length)})` : ""}
            </Button>
          )}
          <Button icon={<ReloadOutlined />} onClick={() => orders.refetch()} />
        </span>
      </div>

      <div className="oc-toolbar">
        <Input.Search allowClear placeholder={t("order.searchHint")} defaultValue={filters.q} style={{ width: 240 }}
          onSearch={(v) => set({ q: v })} />
        <Select mode="multiple" allowClear placeholder={t("common.status")} style={{ minWidth: 220 }}
          value={filters.status ? filters.status.split(",") : []}
          onChange={(v: string[]) => set({ status: v.join(",") })}
          options={STATUSES.map((s) => ({ value: s, label: t(`status.${s}`) }))} />
        <Select allowClear showSearch optionFilterProp="label" placeholder={t("order.checker")} style={{ width: 180 }}
          value={filters.checker ? Number(filters.checker) : undefined}
          onChange={(v) => set({ checker: v ? String(v) : null })}
          options={(checkers.data ?? []).map((c) => ({ value: c.id, label: c.name }))} />
        <DateRange value={filters.from && filters.to ? [filters.from, filters.to] : null}
          onChange={(v) => set({ from: v?.[0] ?? null, to: v?.[1] ?? null })} />
        <Checkbox checked={filters.unassigned === "true"} onChange={(e) => set({ unassigned: e.target.checked ? "true" : null })}>
          {t("order.unassigned")}
        </Checkbox>
        <Checkbox checked={filters.has_issues === "true"} onChange={(e) => set({ has_issues: e.target.checked ? "true" : null })}>
          {t("order.hasIssues")}
        </Checkbox>
      </div>

      <Table<OrderListItem>
        rowKey="id"
        size="middle"
        loading={orders.isLoading}
        dataSource={orders.data?.results ?? []}
        scroll={{ x: 1100 }}
        rowSelection={can("orders.assign") ? {
          selectedRowKeys: selected,
          onChange: (keys) => setSelected(keys as number[]),
          getCheckboxProps: (r) => ({ disabled: !assignable(r) }),
        } : undefined}
        rowClassName={(r) => (r.open_issues ? "oc-row-issue" : "")}
        onRow={(r) => ({ onDoubleClick: () => nav(`/orders/${r.id}`) })}
        pagination={{
          current: page, pageSize: PAGE, total: orders.data?.count ?? 0, showSizeChanger: false,
          showTotal: (n) => `${t("common.total")}: ${num(n)}`, onChange: (p) => set({ page: String(p) }),
        }}
        columns={[
          { title: t("order.reference"), dataIndex: "reference_id", fixed: "left", render: (v, r) => <a onClick={() => nav(`/orders/${r.id}`)}><Ltr>{v}</Ltr></a> },
          { title: t("order.customer"), dataIndex: "customer", ellipsis: true, width: 220 },
          { title: t("order.created"), dataIndex: "source_created_at", render: (v) => dateTime(v) },
          { title: t("common.status"), dataIndex: "status", render: (s) => <StatusTag status={s} /> },
          { title: t("order.checker"), render: (_, r) => r.checker?.name ?? <Tag>{t("order.unassigned")}</Tag> },
          { title: t("order.picker"), dataIndex: "picker_name", render: (v) => v || t("common.none") },
          { title: t("order.lines"), dataIndex: "lines_total", render: (v) => num(v) },
          { title: t("order.boxes"), render: (_, r) => of(r.boxes_scanned, r.boxes_ordered) },
          { title: t("order.progress"), render: (_, r) => <OrderProgress done={r.lines_done} total={r.lines_total} issues={r.open_issues} /> },
          { title: t("order.issues"), render: (_, r) => (r.issues_total ? <Tag color={r.open_issues ? "red" : "orange"}>{num(r.issues_total)}</Tag> : num(0)) },
          { title: t("order.duration"), dataIndex: "duration_seconds", render: (v) => duration(v) },
        ]}
      />

      <AssignModal open={assignOpen} mode="bulk" orderIds={selected} onClose={() => { setAssignOpen(false); setSelected([]); }} />
      <AutoAssignModal open={autoOpen} orderIds={selected} onClose={() => { setAutoOpen(false); setSelected([]); }} />
    </>
  );
}
