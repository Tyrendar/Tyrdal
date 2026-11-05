import { ArrowLeftOutlined, ArrowRightOutlined, ReloadOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Card, Descriptions, Empty, Input, Modal, Space, Table, Tabs, Tag, Timeline, Typography } from "antd";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { get, post, type Page } from "../api/client";
import type { AuditEntry, CheckEventRow, OrderDetail, OrderLine, Tab } from "../api/types";
import { useAuth } from "../auth";
import AssignModal from "../components/AssignModal";
import { DiscrepancyTags, LineStateTag, Ltr, OrderProgress, StatusTag } from "../components/common";
import { useI18n } from "../i18n";

const TABS: Tab[] = ["to_check", "ok", "issue"];

export default function OrderDetailPage() {
  const { id } = useParams();
  const { t, num, dateTime, duration, dir } = useI18n();
  const { can } = useAuth();
  const nav = useNavigate();
  const [assignMode, setAssignMode] = useState<"assign" | "reassign" | null>(null);
  const [tab, setTab] = useState<string | null>(null);

  const order = useQuery({
    queryKey: ["order", id],
    queryFn: () => get<OrderDetail>(`orders/${id}/`),
    refetchInterval: (q) => (q.state.data?.status === "in_progress" ? 10_000 : false),
  });
  const o = order.data;

  if (!o) return <Card loading={order.isLoading}>{order.isError && <Empty />}</Card>;

  const byTab = (k: Tab) => o.lines.filter((l) => l.tab === k);
  const open = o.status !== "completed" && o.status !== "cancelled";
  const active = o.assignments.find((a) => !a.revoked_at);

  return (
    <>
      <div className="oc-page-header">
        <Space>
          <Button icon={dir === "rtl" ? <ArrowRightOutlined /> : <ArrowLeftOutlined />} onClick={() => nav(-1)} />
          <h2>{t("order.reference")} <Ltr copy>{o.reference_id}</Ltr></h2>
          <StatusTag status={o.status} />
          {o.version > 1 && <Tag>{t("order.version")} {num(o.version)}</Tag>}
        </Space>
        <Space wrap>
          {can("orders.assign") && open && !active && <Button type="primary" onClick={() => setAssignMode("assign")}>{t("order.assign")}</Button>}
          {can("orders.assign") && open && active && <Button onClick={() => setAssignMode("reassign")}>{t("order.reassign")}</Button>}
          {can("orders.assign") && open && active && o.status === "assigned" && <NoteAction kind="unassign" orderId={o.id} optional />}
          {can("orders.manage") && open && <NoteAction kind="cancel" orderId={o.id} danger />}
          {can("orders.manage") && o.status === "completed" && <NoteAction kind="reopen" orderId={o.id} />}
          <Button icon={<ReloadOutlined />} onClick={() => order.refetch()} />
        </Space>
      </div>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 4 }}>
          <Descriptions.Item label={t("order.customer")}>{o.customer}</Descriptions.Item>
          <Descriptions.Item label={t("order.type")}><Ltr>{o.reference_type}</Ltr></Descriptions.Item>
          <Descriptions.Item label={t("order.created")}>{dateTime(o.source_created_at)}</Descriptions.Item>
          <Descriptions.Item label={t("order.picker")}>{o.picker_name || t("common.none")}</Descriptions.Item>
          <Descriptions.Item label={t("order.checker")}>{o.checker?.name ?? t("order.unassigned")}</Descriptions.Item>
          <Descriptions.Item label={t("order.started")}>{dateTime(o.first_scan_at)}</Descriptions.Item>
          <Descriptions.Item label={t("order.completed")}>{dateTime(o.completed_at)}</Descriptions.Item>
          <Descriptions.Item label={t("order.completedBy")}>{o.completed_by_name ?? t("common.none")}</Descriptions.Item>
          <Descriptions.Item label={t("order.duration")}>{duration(o.duration_seconds)}</Descriptions.Item>
          <Descriptions.Item label={t("order.boxes")}>{num(o.boxes_scanned)} / {num(o.boxes_ordered)}</Descriptions.Item>
          <Descriptions.Item label={t("order.issues")}>{num(o.issues_total)} ({t("order.openIssues")}: {num(o.open_issues)})</Descriptions.Item>
          <Descriptions.Item label={t("order.progress")}><OrderProgress done={o.lines_done} total={o.lines_total} issues={o.open_issues} /></Descriptions.Item>
        </Descriptions>
      </Card>

      <Card size="small">
        <Tabs
          activeKey={tab ?? (open ? "to_check" : "issue")}
          onChange={setTab}
          items={[
            ...TABS.map((k) => ({
              key: k,
              label: (
                <span>
                  {t(`tab.${k}`)}{" "}
                  <Tag bordered={false} color={k === "issue" ? "red" : k === "ok" ? "green" : "default"} style={{ marginInlineStart: 4 }}>{num(byTab(k).length)}</Tag>
                </span>
              ),
              children: <LinesTable lines={byTab(k)} tab={k} />,
            })),
            { key: "timeline", label: t("order.timeline"), children: <EventsTable orderId={o.id} /> },
            {
              key: "assignments", label: t("order.assignments"),
              children: (
                <Timeline items={o.assignments.map((a) => ({
                  color: a.revoked_at ? "gray" : "green",
                  children: (
                    <>
                      <Typography.Text strong>{a.checker_name}</Typography.Text> — {dateTime(a.assigned_at)}
                      {a.assigned_by_name && <Typography.Text type="secondary"> · {t("order.assignedBy")}: {a.assigned_by_name}</Typography.Text>}
                      {a.revoked_at && <div><Typography.Text type="secondary">{t("order.revoked")}: {dateTime(a.revoked_at)} {a.revoked_by_name ? `· ${a.revoked_by_name}` : ""} {a.revoke_reason ? `· ${a.revoke_reason}` : ""}</Typography.Text></div>}
                    </>
                  ),
                }))} />
              ),
            },
            ...(can("audit.view") ? [{ key: "audit", label: t("order.audit"), children: <OrderAudit orderId={o.id} /> }] : []),
          ]}
        />
      </Card>

      <AssignModal open={assignMode !== null} mode={assignMode ?? "assign"} orderIds={[o.id]} currentCheckerId={active?.checker_id}
        onClose={() => setAssignMode(null)} />
    </>
  );
}

function LinesTable({ lines, tab }: { lines: OrderLine[]; tab: Tab }) {
  const { t, num, dateTime } = useI18n();
  const [q, setQ] = useState("");
  const needle = q.trim().toLowerCase();
  const rows = needle
    ? lines.filter((l) => l.title.toLowerCase().includes(needle) || l.product_id.includes(needle) || l.barcodes.some((b) => b.includes(needle)) || l.aisle_title.toLowerCase().includes(needle))
    : lines;
  return (
    <>
      <Input.Search allowClear placeholder={t("barcodes.searchHint")} style={{ maxWidth: 320, marginBottom: 8 }} onChange={(e) => setQ(e.target.value)} />
      <Table<OrderLine>
        rowKey="id" size="small" dataSource={rows} scroll={{ x: 1100 }}
        pagination={{ pageSize: 100, showSizeChanger: false, hideOnSinglePage: true }}
        columns={[
          { title: t("line.product"), dataIndex: "title", width: 280, render: (v, l) => <>{v}{l.is_unordered && <Tag color="magenta" style={{ marginInlineStart: 6 }}>{t("lineState.extra")}</Tag>}</> },
          { title: t("line.productId"), dataIndex: "product_id", render: (v) => <Ltr>{v}</Ltr> },
          { title: t("line.barcode"), dataIndex: "barcodes", render: (bs: string[]) => <Space direction="vertical" size={0}>{bs.map((b) => <Ltr key={b}>{b}</Ltr>)}</Space> },
          { title: t("line.aisle"), dataIndex: "aisle_title", sorter: (a, b) => a.aisle_rank - b.aisle_rank, render: (v) => <Ltr>{v}</Ltr> },
          { title: t("line.ordered"), dataIndex: "pack_ordered", render: (v) => num(v) },
          { title: t("line.inc"), dataIndex: "inc_ordered", render: (v) => num(v) },
          { title: t("line.scanned"), dataIndex: "boxes_scanned", render: (v) => num(v) },
          tab === "to_check"
            ? { title: t("line.remaining"), render: (_, l) => <Typography.Text strong>{num(l.boxes_short)}</Typography.Text> }
            : { title: t("line.unitsEq"), dataIndex: "units_scanned", render: (v) => num(v) },
          ...(tab === "issue" ? [
            { title: t("line.short"), render: (_: unknown, l: OrderLine) => (l.boxes_short && !l.is_unordered ? <Typography.Text type="danger">{num(l.boxes_short)} ({num(l.boxes_short * l.inc_ordered)} {t("common.units")})</Typography.Text> : t("common.none")) },
            { title: t("line.extra"), dataIndex: "boxes_extra", render: (v: number) => (v ? <Typography.Text style={{ color: "#9333ea" }}>{num(v)}</Typography.Text> : t("common.none")) },
            { title: t("line.discrepancy"), render: (_: unknown, l: OrderLine) => <DiscrepancyTags items={l.discrepancies} /> },
          ] : []),
          { title: t("line.state"), dataIndex: "state", render: (s) => <LineStateTag state={s} /> },
          { title: t("line.stock"), dataIndex: "physical_stock", render: (v) => num(v) },
          { title: t("event.at"), dataIndex: "last_scan_at", render: (v) => dateTime(v) },
        ]}
      />
    </>
  );
}

function EventsTable({ orderId }: { orderId: number }) {
  const { t, num, dateTime } = useI18n();
  const [page, setPage] = useState(1);
  const ev = useQuery({ queryKey: ["order-events", orderId, page], queryFn: () => get<Page<CheckEventRow>>(`orders/${orderId}/events/?limit=50&offset=${(page - 1) * 50}`) });
  const color: Record<string, string> = { counted: "green", duplicate: "default", over_pending: "orange", not_in_order_pending: "magenta", unknown: "red", removed: "purple", mistake: "default", blocked: "red", locked: "red", invalid: "red", applied: "blue" };
  return (
    <Table<CheckEventRow>
      rowKey="id" size="small" loading={ev.isLoading} dataSource={ev.data?.results ?? []} scroll={{ x: 900 }}
      pagination={{ current: page, pageSize: 50, total: ev.data?.count ?? 0, onChange: setPage, showSizeChanger: false }}
      columns={[
        { title: t("event.at"), dataIndex: "at", render: (v) => dateTime(v) },
        { title: t("common.actions"), dataIndex: "kind", render: (v) => t(`event.kind.${v}`, v) },
        { title: t("common.status"), dataIndex: "result", render: (v, r) => <><Tag color={color[v]}>{t(`event.result.${v}`, v)}</Tag>{r.is_late && <Tag>{t("event.late")}</Tag>}</> },
        { title: t("line.barcode"), dataIndex: "barcode", render: (v) => (v ? <Ltr>{v}</Ltr> : t("common.none")) },
        { title: t("line.product"), dataIndex: "title", ellipsis: true, render: (v, r) => v ?? (r.product_id ? <Ltr>{r.product_id}</Ltr> : t("common.none")) },
        { title: "Δ", dataIndex: "delta_boxes", render: (v) => (v ? num(v) : "") },
        { title: t("event.user"), dataIndex: "user" },
      ]}
    />
  );
}

function OrderAudit({ orderId }: { orderId: number }) {
  const { t, dateTime } = useI18n();
  const a = useQuery({ queryKey: ["order-audit", orderId], queryFn: () => get<Page<AuditEntry>>(`orders/${orderId}/audit/?limit=200`) });
  return (
    <Table<AuditEntry>
      rowKey="id" size="small" loading={a.isLoading} dataSource={a.data?.results ?? []} pagination={false} scroll={{ x: 800 }}
      columns={[
        { title: t("event.at"), dataIndex: "at", render: (v) => dateTime(v) },
        { title: t("event.user"), dataIndex: "user" },
        { title: t("audit.action"), dataIndex: "action", render: (v) => <Ltr>{v}</Ltr> },
        { title: t("common.note"), dataIndex: "note" },
        { title: t("common.details"), render: (_, r) => <JsonDiff before={r.before} after={r.after} /> },
      ]}
    />
  );
}

export function JsonDiff({ before, after }: { before: unknown; after: unknown }) {
  const { t } = useI18n();
  const s = (v: unknown) => (v === null || v === undefined ? "" : JSON.stringify(v));
  return (
    <div style={{ fontSize: 12 }}>
      {before != null && <div><Typography.Text type="secondary">{t("common.before")}: </Typography.Text><Ltr>{s(before)}</Ltr></div>}
      {after != null && <div><Typography.Text type="secondary">{t("common.after")}: </Typography.Text><Ltr>{s(after)}</Ltr></div>}
    </div>
  );
}

function NoteAction({ kind, orderId, danger, optional }: { kind: "cancel" | "reopen" | "unassign"; orderId: number; danger?: boolean; optional?: boolean }) {
  const { t, error } = useI18n();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const m = useMutation({
    mutationFn: () => post(`orders/${orderId}/${kind}/`, kind === "unassign" ? { reason: note } : { note }),
    onSuccess: () => { message.success(t("common.saved")); setOpen(false); setNote(""); qc.invalidateQueries({ queryKey: ["order"] }); qc.invalidateQueries({ queryKey: ["orders"] }); qc.invalidateQueries({ queryKey: ["summary"] }); },
    onError: (e) => message.error(error(e)),
  });
  const label = kind === "cancel" ? t("order.cancel") : kind === "reopen" ? t("order.reopen") : t("order.unassign");
  const confirmText = kind === "cancel" ? t("order.cancelConfirm") : kind === "reopen" ? t("order.reopenConfirm") : "";
  return (
    <>
      <Button danger={danger} onClick={() => setOpen(true)}>{label}</Button>
      <Modal open={open} title={label} onCancel={() => setOpen(false)} okButtonProps={{ danger, disabled: !optional && !note.trim(), loading: m.isPending }}
        okText={t("common.confirm")} cancelText={t("common.cancel")} onOk={() => m.mutate()} destroyOnHidden>
        {confirmText && <p>{confirmText}</p>}
        <Input.TextArea rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder={optional ? t("order.reasonOptional") : t("order.noteRequired")} maxLength={500} />
      </Modal>
    </>
  );
}
