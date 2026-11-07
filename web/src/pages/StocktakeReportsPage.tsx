import { DownloadOutlined, InfoCircleOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { App, Button, Card, Col, Row, Segmented, Select, Statistic, Table, Tabs, Tag, Typography } from "antd";
import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { download, get, qs } from "../api/client";
import { DateRange, presetRange, type Preset } from "../components/DateRange";
import { Ltr } from "../components/common";
import { useI18n } from "../i18n";
import { useStocktakers, useVendors } from "./StocktakesPage";

type TabKey = "overview" | "counters" | "vendors" | "stocktakes" | "new-titles";
const byNum = <T,>(k: keyof T) => (a: T, b: T) => ((a[k] as number | null) ?? -Infinity) - ((b[k] as number | null) ?? -Infinity);

interface Overview {
  records: number; units: number; barcodes: number; counters: number; vendors: number; stocktakes_counted: number;
  typed_titles: number; with_price: number; without_title: number; value: number | string; stocktakes_planned: number;
  stocktakes_closed: number; active_seconds: number; records_per_hour: number | null;
  now: { open: number; upcoming: number; counting_today: number; new_titles_to_review: number };
  by_day: { date: string; records: number; units: number; counters: number }[];
}
type Row = Record<string, unknown>;

function useReport<T>(name: string, query: string, enabled: boolean) {
  return useQuery({ queryKey: ["st-report", name, query], queryFn: () => get<T>(`stocktake-reports/${name}/${query}`), enabled, staleTime: 15_000 });
}

/** Stocktaking reports — separate from the order-checking reports. */
export default function StocktakeReportsPage() {
  const { t, calendar, lang, date, error } = useI18n();
  const { message } = App.useApp();
  const [sp, setSp] = useSearchParams();
  const tab = (sp.get("tab") as TabKey) || "overview";
  const preset = (sp.get("p") as Preset | "custom") || "today";
  const [custom, setCustom] = useState<[string, string] | null>(null);
  const [vendor, setVendor] = useState<number | undefined>();
  const [counter, setCounter] = useState<number | undefined>();
  const [busy, setBusy] = useState(false);
  const vendors = useVendors();
  const counters = useStocktakers();

  const range = useMemo<[string, string]>(
    () => (preset === "custom" ? custom ?? presetRange("today", calendar) : presetRange(preset, calendar)),
    [preset, custom, calendar],
  );
  const params = { from: range[0], to: range[1], vendor: tab === "new-titles" ? undefined : vendor, counter };
  const query = qs(params);
  const setParam = (k: string, v: string) => { const n = new URLSearchParams(sp); n.set(k, v); setSp(n, { replace: true }); };
  const exportXlsx = async () => {
    setBusy(true);
    try { await download(`stocktake-reports/${tab}/${qs({ ...params, export: "xlsx", lang })}`, `stocktake_${tab}.xlsx`); }
    catch (e) { message.error(error(e)); }
    finally { setBusy(false); }
  };

  return (
    <>
      <div className="oc-page-header">
        <h2>{t("menu.stReports")}</h2>
        <Button icon={<DownloadOutlined />} loading={busy} onClick={exportXlsx}>{t("reports.export")}</Button>
      </div>
      <div className="oc-toolbar">
        <Segmented value={preset} onChange={(v) => setParam("p", String(v))}
          options={(["today", "week", "month", "custom"] as const).map((k) => ({ value: k, label: t(`reports.${k}`) }))} />
        {preset === "custom" && <DateRange value={custom} onChange={setCustom} />}
        <Typography.Text type="secondary">{date(range[0] + "T12:00:00")} – {date(range[1] + "T12:00:00")}</Typography.Text>
        {tab !== "new-titles" && (
          <Select allowClear showSearch optionFilterProp="label" placeholder={t("stocktake.allVendors")} style={{ width: 200 }}
            value={vendor} onChange={setVendor} options={(vendors.data ?? []).map((v) => ({ value: v.id, label: v.name }))} />
        )}
        <Select allowClear showSearch optionFilterProp="label" placeholder={t("stReports.allCounters")} style={{ width: 190 }}
          value={counter} onChange={setCounter} options={(counters.data ?? []).map((c) => ({ value: c.id, label: c.name }))} />
      </div>
      <Tabs
        activeKey={tab}
        onChange={(k) => setParam("tab", k)}
        items={[
          { key: "overview", label: t("stReports.tabs.overview"), children: <OverviewTab query={query} enabled={tab === "overview"} /> },
          { key: "counters", label: t("stReports.tabs.counters"), children: <CountersTab query={query} enabled={tab === "counters"} /> },
          { key: "vendors", label: t("stReports.tabs.vendors"), children: <VendorsTab query={query} enabled={tab === "vendors"} /> },
          { key: "stocktakes", label: t("stReports.tabs.stocktakes"), children: <StocktakesTab query={query} enabled={tab === "stocktakes"} /> },
          { key: "new-titles", label: t("stReports.tabs.newTitles"), children: <NewTitlesTab query={query} enabled={tab === "new-titles"} /> },
        ]}
      />
    </>
  );
}

function Stat({ title, value, color, onClick }: { title: string; value: string; color?: string; onClick?: () => void }) {
  return (
    <Col flex="1 1 170px">
      <Card size="small" className={onClick ? "oc-stat" : undefined} onClick={onClick} style={{ borderTop: `3px solid ${color ?? "#0f766e"}` }}>
        <Statistic title={title} value={value} valueStyle={{ color, fontWeight: 700, fontSize: 22 }} />
      </Card>
    </Col>
  );
}

const useMoney = () => {
  const { lang, t } = useI18n();
  return (v: unknown) => (v === null || v === undefined ? t("common.none")
    : new Intl.NumberFormat(lang === "fa" ? "fa-IR" : "en-US", { maximumFractionDigits: 0 }).format(Number(v)));
};
const useDec = () => {
  const { lang, t } = useI18n();
  return (v: unknown) => (v === null || v === undefined ? t("common.none") : new Intl.NumberFormat(lang === "fa" ? "fa-IR" : "en-US", { maximumFractionDigits: 1 }).format(Number(v)));
};

function OverviewTab({ query, enabled }: { query: string; enabled: boolean }) {
  const { t, num, duration, date } = useI18n();
  const nav = useNavigate();
  const money = useMoney();
  const dec = useDec();
  const r = useReport<Overview>("overview", query, enabled);
  const d = r.data;
  if (!d) return null;
  return (
    <>
      <Typography.Title level={5}>{t("reports.now")}</Typography.Title>
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Stat title={t("stReports.openNow")} value={num(d.now.open)} onClick={() => nav("/stocktaking")} />
        <Stat title={t("stReports.upcoming")} value={num(d.now.upcoming)} color="#64748b" />
        <Stat title={t("stReports.countingToday")} value={num(d.now.counting_today)} color="#2563eb" />
        <Stat title={t("stReports.titlesToReview")} value={num(d.now.new_titles_to_review)} color="#c2410c" onClick={() => nav("/stocktaking/master")} />
      </Row>
      <Typography.Title level={5}>{t("reports.period")}</Typography.Title>
      <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
        <Stat title={t("stReports.stocktakesPlanned")} value={`${num(d.stocktakes_planned)} (${num(d.stocktakes_closed)} ${t("stReports.closed")})`} />
        <Stat title={t("stReports.records")} value={num(d.records)} />
        <Stat title={t("stReports.units")} value={num(d.units)} />
        <Stat title={t("stReports.barcodes")} value={num(d.barcodes)} />
        <Stat title={t("stReports.counters")} value={num(d.counters)} />
        <Stat title={t("stReports.vendors")} value={num(d.vendors)} />
        <Stat title={t("stReports.activeTime")} value={duration(d.active_seconds)} />
        <Stat title={t("stReports.recordsPerHour")} value={dec(d.records_per_hour)} />
        <Stat title={t("stReports.typedTitles")} value={num(d.typed_titles)} color="#c2410c" />
        <Stat title={t("stReports.withPrice")} value={num(d.with_price)} />
        <Stat title={t("stReports.value")} value={money(d.value)} />
      </Row>
      <Typography.Paragraph type="secondary"><InfoCircleOutlined /> {t("stReports.hint")}</Typography.Paragraph>
      <Card size="small" title={t("reports.byDay")}>
        <Table rowKey="date" size="small" pagination={false} dataSource={d.by_day}
          columns={[
            { title: t("reports.date"), dataIndex: "date", render: (v) => date(v + "T12:00:00") },
            { title: t("stReports.records"), dataIndex: "records", render: num },
            { title: t("stReports.units"), dataIndex: "units", render: num },
            { title: t("stReports.counters"), dataIndex: "counters", render: num },
          ]} />
      </Card>
    </>
  );
}

function CountersTab({ query, enabled }: { query: string; enabled: boolean }) {
  const { t, num, duration, dateTime } = useI18n();
  const dec = useDec();
  const r = useReport<{ rows: Row[] }>("counters", query, enabled);
  const n = (k: string, title: string, color?: string) => ({
    title, dataIndex: k, sorter: byNum<Row>(k), render: (v: number) => (color && v ? <Typography.Text style={{ color }}>{num(v)}</Typography.Text> : num(v)),
  });
  return (
    <Table<Row> className="oc-nowrap" rowKey="user_id" size="middle" loading={r.isLoading} dataSource={r.data?.rows ?? []}
      tableLayout="auto" scroll={{ x: "max-content" }} pagination={false}
      columns={[
        { title: t("stocktake.counter"), dataIndex: "name", fixed: "left", width: 150 },
        n("stocktakes", t("stReports.stocktakes")), n("records", t("stReports.records")), n("units", t("stReports.units")),
        n("barcodes", t("stReports.barcodes")),
        { title: t("stReports.activeTime"), dataIndex: "active_seconds", sorter: byNum<Row>("active_seconds"), render: (v) => duration(v as number) },
        { title: t("stReports.recordsPerHour"), dataIndex: "records_per_hour", sorter: byNum<Row>("records_per_hour"), defaultSortOrder: "descend", render: (v) => <b>{dec(v)}</b> },
        { title: t("stReports.unitsPerHour"), dataIndex: "units_per_hour", sorter: byNum<Row>("units_per_hour"), render: dec },
        n("typed_titles", t("stReports.typedTitles"), "#c2410c"), n("edited", t("stReports.edited")), n("deleted", t("stReports.deleted"), "#dc2626"),
        { title: t("stReports.firstAt"), dataIndex: "first_at", render: (v) => dateTime(v as string) },
        { title: t("stReports.lastAt"), dataIndex: "last_at", render: (v) => dateTime(v as string) },
      ]} />
  );
}

function VendorsTab({ query, enabled }: { query: string; enabled: boolean }) {
  const { t, num, dateTime } = useI18n();
  const money = useMoney();
  const r = useReport<{ rows: Row[] }>("vendors", query, enabled);
  return (
    <Table<Row> className="oc-nowrap" rowKey="vendor_id" size="middle" loading={r.isLoading} dataSource={r.data?.rows ?? []}
      tableLayout="auto" scroll={{ x: "max-content" }} pagination={false}
      columns={[
        { title: t("stocktake.vendor"), dataIndex: "vendor", fixed: "left", render: (v) => <b>{v as string}</b> },
        { title: t("stReports.stocktakes"), dataIndex: "stocktakes", render: num },
        { title: t("stReports.records"), dataIndex: "records", sorter: byNum<Row>("records"), render: num },
        { title: t("stReports.units"), dataIndex: "units", sorter: byNum<Row>("units"), defaultSortOrder: "descend", render: (v) => <b>{num(v as number)}</b> },
        { title: t("stReports.barcodes"), dataIndex: "barcodes", sorter: byNum<Row>("barcodes"), render: num },
        { title: t("stReports.counters"), dataIndex: "counters", render: num },
        { title: t("stReports.withPrice"), dataIndex: "with_price", render: num },
        { title: t("stReports.value"), dataIndex: "value", sorter: (a, b) => Number(a.value) - Number(b.value), render: money },
        { title: t("stReports.lastAt"), dataIndex: "last_at", render: (v) => dateTime(v as string) },
      ]} />
  );
}

function StocktakesTab({ query, enabled }: { query: string; enabled: boolean }) {
  const { t, num, date, dateTime, duration } = useI18n();
  const nav = useNavigate();
  const r = useReport<{ rows: Row[] }>("stocktakes", query, enabled);
  return (
    <Table<Row> className="oc-nowrap" rowKey="stocktake_id" size="small" loading={r.isLoading} dataSource={r.data?.rows ?? []}
      tableLayout="auto" scroll={{ x: "max-content" }} pagination={{ pageSize: 50, showSizeChanger: false }}
      onRow={(x) => ({ onClick: () => nav(`/stocktaking/${x.stocktake_id}`), style: { cursor: "pointer" } })}
      columns={[
        { title: t("stocktake.vendor"), dataIndex: "vendor", fixed: "left", render: (v) => <b>{v as string}</b> },
        { title: t("stocktake.date"), dataIndex: "date", render: (v) => date((v as string) + "T12:00:00") },
        { title: t("common.status"), dataIndex: "status", render: (v) => <Tag color={v === "open" ? "processing" : "default"}>{t(`stocktake.status.${v}`)}</Tag> },
        { title: t("stocktake.counters"), dataIndex: "counters", render: (v) => <span className="oc-clip" title={v as string}>{v as string}</span> },
        { title: t("stReports.records"), dataIndex: "records", sorter: byNum<Row>("records"), render: num },
        { title: t("stReports.units"), dataIndex: "units", sorter: byNum<Row>("units"), render: (v) => <b>{num(v as number)}</b> },
        { title: t("stReports.barcodes"), dataIndex: "barcodes", render: num },
        { title: t("stReports.typedTitles"), dataIndex: "typed_titles", render: num },
        { title: t("stReports.firstAt"), dataIndex: "first_at", render: (v) => dateTime(v as string) },
        { title: t("stReports.lastAt"), dataIndex: "last_at", render: (v) => dateTime(v as string) },
        { title: t("stReports.elapsed"), dataIndex: "elapsed_seconds", sorter: byNum<Row>("elapsed_seconds"), render: (v) => duration(v as number) },
        { title: t("stReports.closedAt"), dataIndex: "closed_at", render: (v) => dateTime(v as string) },
      ]} />
  );
}

function NewTitlesTab({ query, enabled }: { query: string; enabled: boolean }) {
  const { t, dateTime } = useI18n();
  const r = useReport<{ rows: Row[] }>("new-titles", query, enabled);
  return (
    <>
      <Typography.Paragraph type="secondary"><InfoCircleOutlined /> {t("stReports.newTitlesHint")}</Typography.Paragraph>
      <Table<Row> className="oc-nowrap" rowKey="id" size="small" loading={r.isLoading} dataSource={r.data?.rows ?? []}
        tableLayout="auto" scroll={{ x: "max-content" }} pagination={{ pageSize: 100, showSizeChanger: false }}
        rowClassName={(x) => (x.deleted ? "oc-row-deleted" : "")}
        columns={[
          { title: t("master.barcode"), dataIndex: "barcode", render: (v) => <Ltr>{v as string}</Ltr> },
          { title: t("stReports.typedTitle"), dataIndex: "title", render: (v) => <b>{v as string}</b> },
          { title: t("stReports.otherTitles"), dataIndex: "other_titles", render: (v) => (v ? <span className="oc-clip" title={v as string}>{v as string}</span> : t("common.none")) },
          { title: t("stocktake.counter"), dataIndex: "counter" },
          { title: t("stocktake.time"), dataIndex: "created_at", render: (v) => dateTime(v as string) },
        ]} />
    </>
  );
}
