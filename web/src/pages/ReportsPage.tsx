import { DownloadOutlined, InfoCircleOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { App, Button, Card, Col, Input, Row, Segmented, Select, Statistic, Table, Tabs, Tag, Tooltip, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { download, get, qs } from "../api/client";
import type { CheckerReportRow, OperationsRow, OrderStatus, PickerReportRow, ReasonReportRow, ReportOverview } from "../api/types";
import { useCheckers } from "../components/AssignModal";
import { DateRange, presetRange, type Preset } from "../components/DateRange";
import { Ltr, StatusTag } from "../components/common";
import { useI18n } from "../i18n";

type TabKey = "overview" | "checkers" | "pickers" | "reasons" | "operations";
const STATUSES: OrderStatus[] = ["pending_assignment", "assigned", "in_progress", "completed", "cancelled"];

/** Sorts numbers with nulls last, so "no data" never ranks first. */
const byNum = <T,>(k: keyof T) => (a: T, b: T) => ((a[k] as number | null) ?? -Infinity) - ((b[k] as number | null) ?? -Infinity);

export default function ReportsPage() {
  const { t, calendar, lang, date, error } = useI18n();
  const { message } = App.useApp();
  const [sp, setSp] = useSearchParams();
  const checkers = useCheckers();
  const tab = (sp.get("tab") as TabKey) || "overview";
  const preset = (sp.get("p") as Preset | "custom") || "today";
  const [custom, setCustom] = useState<[string, string] | null>(null);
  const [checker, setChecker] = useState<number | undefined>();
  const [picker, setPicker] = useState<string | undefined>();
  const [status, setStatus] = useState<string[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);

  const range = useMemo<[string, string]>(
    () => (preset === "custom" ? custom ?? presetRange("today", calendar) : presetRange(preset, calendar)),
    [preset, custom, calendar],
  );
  const params = {
    from: range[0], to: range[1], checker: tab === "pickers" ? undefined : checker,
    picker: tab === "reasons" ? picker : undefined,
    status: tab === "operations" && status.length ? status.join(",") : undefined,
    q: tab === "operations" ? q : undefined,
  };
  const query = qs(params);
  const setParam = (k: string, v: string) => { const n = new URLSearchParams(sp); n.set(k, v); setSp(n, { replace: true }); };

  const exportXlsx = async () => {
    setBusy(true);
    try { await download(`reports/${tab}/${qs({ ...params, export: "xlsx", lang })}`, `${tab}.xlsx`); }
    catch (e) { message.error(error(e)); }
    finally { setBusy(false); }
  };

  return (
    <>
      <div className="oc-page-header">
        <h2>{t("menu.reports")}</h2>
        <Button icon={<DownloadOutlined />} loading={busy} onClick={exportXlsx}>{t("reports.export")}</Button>
      </div>
      <div className="oc-toolbar">
        <Segmented value={preset} onChange={(v) => setParam("p", String(v))}
          options={(["today", "week", "month", "custom"] as const).map((k) => ({ value: k, label: t(`reports.${k}`) }))} />
        {preset === "custom" && <DateRange value={custom} onChange={setCustom} />}
        <Typography.Text type="secondary">{date(range[0] + "T12:00:00")} – {date(range[1] + "T12:00:00")}</Typography.Text>
        {tab !== "pickers" && (
          <Select allowClear showSearch optionFilterProp="label" placeholder={t("reports.allCheckers")} style={{ width: 190 }}
            value={checker} onChange={setChecker} options={(checkers.data ?? []).map((c) => ({ value: c.id, label: c.name }))} />
        )}
      </div>
      <Tabs
        activeKey={tab}
        onChange={(k) => setParam("tab", k)}
        items={[
          { key: "overview", label: t("reports.tabs.overview"), children: <Overview query={query} enabled={tab === "overview"} /> },
          { key: "checkers", label: t("reports.tabs.checkers"), children: <Checkers query={query} enabled={tab === "checkers"} /> },
          { key: "pickers", label: t("reports.tabs.pickers"), children: <Pickers query={query} enabled={tab === "pickers"} /> },
          {
            key: "reasons", label: t("reports.tabs.reasons"),
            children: <Reasons query={query} enabled={tab === "reasons"} range={range} picker={picker} setPicker={setPicker} />,
          },
          {
            key: "operations", label: t("reports.tabs.operations"),
            children: (
              <>
                <div className="oc-toolbar">
                  <Input.Search allowClear placeholder={t("order.searchHint")} style={{ width: 240 }} onSearch={setQ} />
                  <Select mode="multiple" allowClear placeholder={t("common.status")} style={{ minWidth: 240 }} value={status} onChange={setStatus}
                    options={STATUSES.map((s) => ({ value: s, label: t(`status.${s}`) }))} />
                </div>
                <Operations query={query} enabled={tab === "operations"} />
              </>
            ),
          },
        ]}
      />
    </>
  );
}

function useReport<T>(name: string, query: string, enabled: boolean) {
  return useQuery({ queryKey: ["report", name, query], queryFn: () => get<T>(`reports/${name}/${query}`), enabled, staleTime: 15_000 });
}

function Stat({ title, value, color }: { title: string; value: string; color?: string }) {
  return (
    <Col flex="1 1 170px">
      <Card size="small" style={{ borderTop: `3px solid ${color ?? "#0f766e"}` }}>
        <Statistic title={title} value={value} valueStyle={{ color, fontWeight: 700, fontSize: 22 }} />
      </Card>
    </Col>
  );
}

function Overview({ query, enabled }: { query: string; enabled: boolean }) {
  const { t, num, of, duration, date, lang } = useI18n();
  const r = useReport<ReportOverview>("overview", query, enabled);
  const d = r.data;
  if (!d) return <Card loading />;
  const sec = (v: number | null) => (v === null ? t("common.none") : new Intl.NumberFormat(lang === "fa" ? "fa-IR" : "en-US").format(v));
  return (
    <>
      <Typography.Title level={5}>{t("reports.now")}</Typography.Title>
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Stat title={t("reports.waiting_assignment")} value={num(d.now.waiting_assignment)} color="#64748b" />
        <Stat title={t("reports.assigned_not_started")} value={num(d.now.assigned_not_started)} color="#2563eb" />
        <Stat title={t("reports.in_progress")} value={num(d.now.in_progress)} color="#0f766e" />
        <Stat title={t("reports.unresolved")} value={num(d.now.unresolved_discrepancies)} color="#dc2626" />
      </Row>
      <Typography.Title level={5}>{t("reports.period")}</Typography.Title>
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Stat title={t("reports.orders_assigned")} value={num(d.orders_assigned)} />
        <Stat title={t("reports.orders_checked")} value={num(d.orders_checked)} color="#16a34a" />
        <Stat title={t("reports.orders_with_discrepancies")} value={num(d.orders_with_discrepancies)} color="#ea580c" />
        <Stat title={t("reports.skus_checked")} value={num(d.skus_checked)} />
        <Stat title={t("reports.boxes_checked")} value={of(d.boxes_checked, d.boxes_ordered)} />
        <Stat title={t("reports.boxes_scanned")} value={num(d.boxes_scanned)} color="#7c3aed" />
      </Row>
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Stat title={t("reports.discrepancies")} value={num(d.discrepancies)} color="#dc2626" />
        <Stat title={t("reports.shortage_boxes")} value={`${num(d.shortage_boxes)} (${num(d.shortage_units)} ${t("reports.units")})`} color="#dc2626" />
        <Stat title={t("reports.extra_boxes")} value={num(d.extra_boxes)} color="#9333ea" />
        <Stat title={t("reports.not_in_order_boxes")} value={num(d.not_in_order_boxes)} color="#9333ea" />
        <Stat title={t("reports.avg_elapsed")} value={duration(d.avg_elapsed_seconds)} />
        <Stat title={t("reports.avg_active")} value={duration(d.avg_active_seconds)} />
        <Stat title={t("reports.per_sku")} value={sec(d.avg_seconds_per_sku)} />
      </Row>
      <Typography.Paragraph type="secondary"><InfoCircleOutlined /> {t("reports.activeHint")}</Typography.Paragraph>
      <Card size="small" title={t("reports.byDay")}>
        <Table
          rowKey="date" size="small" pagination={false} dataSource={d.by_day}
          columns={[
            { title: t("reports.date"), dataIndex: "date", render: (v) => date(v + "T12:00:00") },
            { title: t("reports.orders_completed"), dataIndex: "orders_completed", render: num },
            { title: t("reports.skus_checked"), dataIndex: "skus", render: num },
            { title: t("reports.boxes_scanned"), dataIndex: "boxes_scanned", render: num },
          ]}
        />
      </Card>
    </>
  );
}

function Checkers({ query, enabled }: { query: string; enabled: boolean }) {
  const { t, num, duration, lang } = useI18n();
  const r = useReport<{ rows: CheckerReportRow[] }>("checkers", query, enabled);
  const dec = (v: number | null) => (v === null ? t("common.none") : new Intl.NumberFormat(lang === "fa" ? "fa-IR" : "en-US", { maximumFractionDigits: 1 }).format(v));
  const n = (k: keyof CheckerReportRow, title: string, color?: string) => ({
    title, dataIndex: k, sorter: byNum<CheckerReportRow>(k),
    render: (v: number) => (color && v ? <Typography.Text style={{ color }}>{num(v)}</Typography.Text> : num(v)),
  });
  const columns: ColumnsType<CheckerReportRow> = [
    { title: t("order.checker"), dataIndex: "name", fixed: "left", width: 150 },
    n("orders_checked", t("reports.orders_checked")),
    n("skus_checked", t("reports.skus_checked")),
    n("boxes_scanned", t("reports.boxes_scanned")),
    { title: t("reports.active_time"), dataIndex: "active_seconds", sorter: byNum("active_seconds"), render: duration },
    { title: <Tooltip title={t("reports.activeHint")}>{t("reports.boxes_per_hour")} <InfoCircleOutlined /></Tooltip>, dataIndex: "boxes_per_hour", sorter: byNum("boxes_per_hour"), defaultSortOrder: "descend", render: (v) => <b>{dec(v)}</b> },
    { title: t("reports.avg_elapsed"), dataIndex: "avg_elapsed_seconds", sorter: byNum("avg_elapsed_seconds"), render: duration },
    { title: t("reports.avg_active"), dataIndex: "avg_active_seconds", sorter: byNum("avg_active_seconds"), render: duration },
    { title: t("reports.per_sku"), dataIndex: "avg_seconds_per_sku", sorter: byNum("avg_seconds_per_sku"), render: dec },
    n("orders_with_discrepancies", t("reports.orders_with_discrepancies")),
    n("shortage_boxes", t("reports.shortage_boxes"), "#dc2626"),
    n("extra_boxes", t("reports.extra_boxes"), "#9333ea"),
    n("not_in_order_boxes", t("reports.not_in_order_boxes"), "#9333ea"),
    n("double_reads", t("reports.double_reads")),
    n("unknown_scans", t("reports.unknown_scans"), "#dc2626"),
    n("mistakes", t("reports.mistakes")),
    n("corrections", t("reports.corrections")),
  ];
  return <Table<CheckerReportRow> className="oc-nowrap" rowKey="checker_id" size="middle" loading={r.isLoading} dataSource={r.data?.rows ?? []} columns={columns} tableLayout="auto" scroll={{ x: "max-content" }} pagination={false} />;
}

function Pickers({ query, enabled }: { query: string; enabled: boolean }) {
  const { t, num, lang } = useI18n();
  const r = useReport<{ rows: PickerReportRow[] }>("pickers", query, enabled);
  const pct = (v: number | null) => (v === null ? t("common.none")
    : new Intl.NumberFormat(lang === "fa" ? "fa-IR" : "en-US", { maximumFractionDigits: 2 }).format(v) + (lang === "fa" ? "٪" : "%"));
  const n = (k: keyof PickerReportRow, title: string, color?: string) => ({
    title, dataIndex: k, sorter: byNum<PickerReportRow>(k),
    render: (v: number) => (color && v ? <Typography.Text style={{ color }}>{num(v)}</Typography.Text> : num(v)),
  });
  return (
    <>
      <Typography.Paragraph type="secondary"><InfoCircleOutlined /> {t("reports.pickerHint")}</Typography.Paragraph>
      <Table<PickerReportRow>
        className="oc-nowrap"
        rowKey="picker" size="middle" loading={r.isLoading} dataSource={r.data?.rows ?? []} pagination={false} tableLayout="auto" scroll={{ x: "max-content" }}
        columns={[
          { title: t("reports.picker"), dataIndex: "picker", fixed: "left", width: 150, render: (v) => v || <Typography.Text type="secondary">{t("reports.noPicker")}</Typography.Text> },
          n("orders", t("menu.orders")),
          n("skus", t("reports.lines")),
          n("boxes_ordered", t("reports.boxes_ordered")),
          n("error_boxes", t("reports.error_boxes"), "#dc2626"),
          { title: t("reports.error_rate"), dataIndex: "error_rate_pct", sorter: byNum("error_rate_pct"), defaultSortOrder: "descend", render: (v) => <b>{pct(v)}</b> },
          n("short_picking_boxes", t("reports.short_picking"), "#dc2626"),
          n("extra_boxes", t("reports.extra_boxes"), "#9333ea"),
          n("not_in_order_boxes", t("reports.not_in_order_boxes"), "#9333ea"),
          n("short_stock_boxes", t("reports.short_stock")),
        ]}
      />
    </>
  );
}

function Reasons({ query, enabled, range, picker, setPicker }: {
  query: string; enabled: boolean; range: [string, string]; picker?: string; setPicker: (v?: string) => void;
}) {
  const { t, num, lang } = useI18n();
  const r = useReport<{ rows: ReasonReportRow[] }>("reasons", query, enabled);
  const pickers = useReport<{ rows: PickerReportRow[] }>("pickers", qs({ from: range[0], to: range[1] }), enabled);
  const total = (r.data?.rows ?? []).reduce((s, x) => s + x.boxes, 0);
  return (
    <>
      <div className="oc-toolbar">
        <Select allowClear placeholder={t("reports.allPickers")} style={{ width: 200 }} value={picker} onChange={setPicker}
          options={(pickers.data?.rows ?? []).map((p) => ({ value: p.picker, label: p.picker || t("reports.noPicker") }))} />
      </div>
      <Table<ReasonReportRow>
        rowKey={(x) => `${x.type}-${x.reason_id}`} size="middle" loading={r.isLoading} dataSource={r.data?.rows ?? []} pagination={false}
        columns={[
          { title: t("reports.type"), dataIndex: "type", render: (v) => <Tag color={v === "short" ? "volcano" : "purple"}>{t(`discType.${v}`)}</Tag> },
          { title: t("common.reason"), render: (_, x) => (lang === "fa" ? x.name_fa : x.name_en) ?? t("common.none") },
          { title: t("reports.category"), dataIndex: "category", render: (v) => (v ? t(`reasons.categories.${v}`) : t("common.none")) },
          { title: t("reports.lines"), dataIndex: "lines", sorter: byNum("lines"), render: num },
          { title: t("reports.boxes"), dataIndex: "boxes", sorter: byNum("boxes"), defaultSortOrder: "descend", render: (v) => <b>{num(v)}</b> },
          { title: "%", render: (_, x) => (total ? num(Math.round((100 * x.boxes) / total)) : t("common.none")) },
          { title: t("reports.units"), dataIndex: "units", sorter: byNum("units"), render: num },
        ]}
      />
    </>
  );
}

function Operations({ query, enabled }: { query: string; enabled: boolean }) {
  const { t, num, of, dateTime, duration } = useI18n();
  const nav = useNavigate();
  const r = useReport<{ rows: OperationsRow[] }>("operations", query, enabled);
  return (
    <Table<OperationsRow>
      className="oc-nowrap"
      rowKey="order_id" size="small" loading={r.isLoading} dataSource={r.data?.rows ?? []} tableLayout="auto" scroll={{ x: "max-content" }}
      pagination={{ pageSize: 50, showSizeChanger: false, showTotal: (n) => `${t("common.total")}: ${num(n)}` }}
      rowClassName={(x) => (x.open_discrepancies ? "oc-row-issue" : "")}
      columns={[
        { title: t("order.reference"), dataIndex: "reference_id", fixed: "left", render: (v, x) => <a onClick={() => nav(`/orders/${x.order_id}`)}><Ltr>{v}</Ltr></a> },
        { title: t("order.customer"), dataIndex: "customer", render: (v) => <span className="oc-clip" title={v}>{v}</span> },
        { title: t("common.status"), dataIndex: "status", render: (s) => <StatusTag status={s} /> },
        { title: t("order.checker"), dataIndex: "checker", render: (v) => v ?? t("common.none") },
        { title: t("reports.picker"), dataIndex: "picker", render: (v) => v || t("common.none") },
        { title: t("reports.imported"), dataIndex: "imported_at", render: dateTime },
        { title: t("reports.assigned"), dataIndex: "assigned_at", render: dateTime },
        { title: t("reports.started"), dataIndex: "started_at", render: dateTime },
        { title: t("reports.completed"), dataIndex: "completed_at", render: dateTime },
        { title: t("reports.wait"), dataIndex: "wait_seconds", sorter: byNum("wait_seconds"), render: duration },
        { title: t("reports.elapsed"), dataIndex: "elapsed_seconds", sorter: byNum("elapsed_seconds"), render: duration },
        { title: t("reports.active_time"), dataIndex: "active_seconds", sorter: byNum("active_seconds"), render: duration },
        { title: t("reports.lines"), render: (_, x) => of(x.skus_done, x.skus) },
        { title: t("reports.boxes"), render: (_, x) => of(x.boxes_scanned, x.boxes_ordered) },
        { title: t("reports.discrepancies"), dataIndex: "discrepancies", sorter: byNum("discrepancies"), render: (v, x) => (v ? <Tag color={x.open_discrepancies ? "red" : "orange"}>{num(v)}</Tag> : num(0)) },
      ]}
    />
  );
}
