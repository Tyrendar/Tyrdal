import { ArrowLeftOutlined, ArrowRightOutlined, DownloadOutlined, EditOutlined, InfoCircleOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Col, Descriptions, Input, Row, Select, Space, Statistic, Switch, Table, Tabs, Tag, Typography } from "antd";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { download, get, post, qs, type Page } from "../api/client";
import type { StockRecord, StocktakeDetail, StockTotal } from "../api/types";
import { Ltr } from "../components/common";
import { useI18n } from "../i18n";
import { StatusTag, StocktakeForm } from "./StocktakesPage";

export default function StocktakeDetailPage() {
  const { id } = useParams();
  const { t, num, date, dateTime, dir, error, lang } = useI18n();
  const { message, modal } = App.useApp();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["stocktake", id], queryFn: () => get<StocktakeDetail>(`stocktakes/${id}/`), refetchInterval: 10_000 });
  const act = useMutation({
    mutationFn: (a: "close" | "reopen") => post(`stocktakes/${id}/${a}/`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["stocktake", id] }); qc.invalidateQueries({ queryKey: ["stocktakes"] }); },
    onError: (e) => message.error(error(e)),
  });
  const s = q.data;
  if (!s) return null;

  const exportFile = async (kind: "wms" | "detail") => {
    setBusy(kind);
    try { await download(`stocktakes/${id}/export/${qs({ kind, lang })}`, `stocktake_${kind}.xlsx`); }
    catch (e) { message.error(error(e)); }
    finally { setBusy(null); }
  };

  return (
    <>
      <div className="oc-page-header">
        <Space align="center">
          <Button type="text" icon={dir === "rtl" ? <ArrowRightOutlined /> : <ArrowLeftOutlined />} onClick={() => nav("/stocktakes")} />
          <h2>{s.vendor.name}</h2>
          <StatusTag status={s.status} />
          {s.status === "open" && (s.countable ? <Tag color="green">{t("stocktake.countable")}</Tag> : <Tag>{t("stocktake.notStarted")}</Tag>)}
        </Space>
        <Space wrap>
          <Button type="primary" icon={<DownloadOutlined />} loading={busy === "wms"} onClick={() => exportFile("wms")}>{t("stocktake.exportWms")}</Button>
          <Button icon={<DownloadOutlined />} loading={busy === "detail"} onClick={() => exportFile("detail")}>{t("stocktake.exportDetail")}</Button>
          {s.status === "open" && <Button icon={<EditOutlined />} onClick={() => setEditing(true)}>{t("common.edit")}</Button>}
          {s.status === "open"
            ? <Button danger loading={act.isPending} onClick={() => modal.confirm({ title: t("stocktake.closeConfirm"), onOk: () => act.mutateAsync("close") })}>{t("stocktake.close")}</Button>
            : <Button loading={act.isPending} onClick={() => modal.confirm({ title: t("stocktake.reopenConfirm"), onOk: () => act.mutateAsync("reopen") })}>{t("stocktake.reopen")}</Button>}
        </Space>
      </div>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 4 }}>
          <Descriptions.Item label={t("stocktake.date")}>{date(s.date + "T12:00:00")}</Descriptions.Item>
          <Descriptions.Item label={t("stocktake.vendorCode")}>{s.vendor.code ? <Ltr>{s.vendor.code}</Ltr> : t("common.none")}</Descriptions.Item>
          <Descriptions.Item label={t("stocktake.counters")}>{s.counters.map((c) => c.name).join("، ") || t("common.none")}</Descriptions.Item>
          <Descriptions.Item label={t("stocktake.note")}>{s.note || t("common.none")}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Stat title={t("stocktake.barcodes")} value={num(s.totals.barcodes)} />
        <Stat title={t("stocktake.quantity")} value={num(s.totals.quantity)} />
        <Stat title={t("stocktake.records")} value={num(s.totals.records)} />
        <Stat title={t("stocktake.priceConflict")} value={num(s.totals.price_conflicts)} color={s.totals.price_conflicts ? "#ca8a04" : undefined} />
        <Stat title={t("stocktake.withoutPrice")} value={num(s.totals.without_price)} />
      </Row>
      <Typography.Paragraph type="secondary"><InfoCircleOutlined /> {t("stocktake.wmsHint")}</Typography.Paragraph>
      {s.totals.price_conflicts > 0 && <Alert type="warning" showIcon style={{ marginBottom: 12 }} message={t("stocktake.priceConflictHint")} />}

      <Card size="small" title={t("stocktake.byCounter")} style={{ marginBottom: 16 }}>
        <Table
          rowKey="user_id" size="small" pagination={false} dataSource={s.by_counter}
          columns={[
            { title: t("stocktake.counter"), dataIndex: "name", render: (v, r) => <>{v}{!r.assigned && <Tag style={{ marginInlineStart: 6 }}>{t("stocktake.notAssigned")}</Tag>}</> },
            { title: t("stocktake.records"), dataIndex: "records", render: num },
            { title: t("stocktake.barcodes"), dataIndex: "barcodes", render: num },
            { title: t("stocktake.quantity"), dataIndex: "quantity", render: (v) => <b>{num(v)}</b> },
            { title: t("stocktake.lastAt"), dataIndex: "last_at", render: dateTime },
          ]}
        />
      </Card>

      <Card size="small">
        <Tabs items={[
          { key: "totals", label: t("stocktake.totalsTab"), children: <Totals id={id!} /> },
          { key: "records", label: t("stocktake.recordsTab"), children: <Records id={id!} counters={s.by_counter} /> },
        ]} />
      </Card>
      <StocktakeForm open={editing} onClose={() => setEditing(false)} initial={s} />
    </>
  );
}

function Stat({ title, value, color }: { title: string; value: string; color?: string }) {
  return (
    <Col flex="1 1 160px">
      <Card size="small" style={{ borderTop: `3px solid ${color ?? "#0f766e"}` }}>
        <Statistic title={title} value={value} valueStyle={{ color, fontWeight: 700, fontSize: 22 }} />
      </Card>
    </Col>
  );
}

function money(v: string | null, lang: string, none: string) {
  if (v === null || v === undefined) return none;
  return new Intl.NumberFormat(lang === "fa" ? "fa-IR" : "en-US", { maximumFractionDigits: 2 }).format(Number(v));
}

function Totals({ id }: { id: string }) {
  const { t, num, lang } = useI18n();
  const [q, setQ] = useState("");
  const [conflicts, setConflicts] = useState(false);
  const query = qs({ q, conflicts: conflicts || undefined });
  const r = useQuery({ queryKey: ["stocktake", id, "totals", query], queryFn: () => get<StockTotal[]>(`stocktakes/${id}/totals/${query}`), refetchInterval: 10_000 });
  return (
    <>
      <div className="oc-toolbar">
        <Input.Search allowClear placeholder={t("stocktake.searchHint")} style={{ width: 260 }} onSearch={setQ} />
        <Space><Switch checked={conflicts} onChange={setConflicts} /> {t("stocktake.onlyConflicts")}</Space>
      </div>
      <Table<StockTotal>
        className="oc-nowrap" rowKey="code" size="small" loading={r.isLoading} dataSource={r.data ?? []} tableLayout="auto" scroll={{ x: "max-content" }}
        pagination={{ pageSize: 100, showSizeChanger: false, showTotal: (n) => `${t("common.total")}: ${num(n)}` }}
        columns={[
          { title: "barcode", dataIndex: "barcode", render: (v) => <Ltr>{v}</Ltr> },
          { title: t("stocktake.product"), dataIndex: "title", render: (v) => (v ? <span className="oc-clip" title={v}>{v}</span> : t("common.none")) },
          { title: "count", dataIndex: "quantity", sorter: (a, b) => a.quantity - b.quantity, render: (v) => <b>{num(v)}</b> },
          { title: "price", dataIndex: "price", render: (v, x) => <>{money(v, lang, t("common.none"))}{x.price_conflict && <Tag color="gold" style={{ marginInlineStart: 6 }}>{t("stocktake.priceConflict")}</Tag>}</> },
          { title: t("stocktake.records"), dataIndex: "records", sorter: (a, b) => a.records - b.records, render: num },
          { title: t("stocktake.counters"), dataIndex: "counters", render: num },
        ]}
      />
    </>
  );
}

function Records({ id, counters }: { id: string; counters: StocktakeDetail["by_counter"] }) {
  const { t, num, dateTime, lang } = useI18n();
  const [q, setQ] = useState("");
  const [counter, setCounter] = useState<number | undefined>();
  const [deleted, setDeleted] = useState(false);
  const [page, setPage] = useState(1);
  const query = qs({ q, counter, deleted: deleted || undefined, page });
  const r = useQuery({ queryKey: ["stocktake", id, "records", query], queryFn: () => get<Page<StockRecord>>(`stocktakes/${id}/records/${query}`), refetchInterval: 10_000 });
  return (
    <>
      <div className="oc-toolbar">
        <Input.Search allowClear placeholder={t("stocktake.searchHint")} style={{ width: 260 }} onSearch={(v) => { setQ(v); setPage(1); }} />
        <Select allowClear placeholder={t("stocktake.counter")} style={{ width: 200 }} value={counter} onChange={(v) => { setCounter(v); setPage(1); }}
          options={counters.map((c) => ({ value: c.user_id, label: c.name }))} />
        <Space><Switch checked={deleted} onChange={(v) => { setDeleted(v); setPage(1); }} /> {t("stocktake.showDeleted")}</Space>
      </div>
      <Table<StockRecord>
        className="oc-nowrap" rowKey="id" size="small" loading={r.isLoading} dataSource={r.data?.results ?? []} tableLayout="auto" scroll={{ x: "max-content" }}
        rowClassName={(x) => (x.deleted ? "oc-row-deleted" : "")}
        pagination={{ current: page, pageSize: 100, total: r.data?.count, onChange: setPage, showSizeChanger: false,
          showTotal: (n) => `${t("common.total")}: ${num(n)}` }}
        columns={[
          { title: t("stocktake.time"), dataIndex: "counted_at", render: dateTime },
          { title: t("stocktake.counter"), dataIndex: "user" },
          { title: "barcode", dataIndex: "barcode", render: (v) => <Ltr>{v}</Ltr> },
          { title: t("stocktake.product"), dataIndex: "title", render: (v) => (v ? <span className="oc-clip" title={v}>{v}</span> : t("common.none")) },
          { title: "count", dataIndex: "quantity", render: (v) => <b>{num(v)}</b> },
          { title: "price", dataIndex: "price", render: (v) => money(v, lang, t("common.none")) },
          { title: "", dataIndex: "deleted", render: (v) => (v ? <Tag>{t("stocktake.deleted")}</Tag> : null) },
        ]}
      />
    </>
  );
}
