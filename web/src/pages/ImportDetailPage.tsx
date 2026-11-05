import { ArrowLeftOutlined, ArrowRightOutlined, CheckOutlined, DeleteOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Col, Popconfirm, Row, Segmented, Space, Statistic, Table, Tag, Typography } from "antd";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { get, post, type Page } from "../api/client";
import type { ImportBatch, ImportOrderPreview, ImportRow } from "../api/types";
import { Ltr, ProblemList } from "../components/common";
import { useI18n } from "../i18n";
import { IMPORT_STATUS_COLOR } from "./ImportsPage";

const ACTION_COLOR: Record<string, string> = {
  new: "green", unchanged: "default", info_updated: "blue", replace: "gold", blocked_started: "red", blocked_closed: "red", invalid: "red",
};
const APPLIED = new Set(["new", "info_updated", "replace"]);

export default function ImportDetailPage() {
  const { id } = useParams();
  const { t, num, dateTime, dir, error } = useI18n();
  const { message } = App.useApp();
  const nav = useNavigate();
  const qc = useQueryClient();
  const batch = useQuery({ queryKey: ["import", id], queryFn: () => get<ImportBatch>(`imports/${id}/`) });

  const act = useMutation({
    mutationFn: (what: "commit" | "discard") => post<ImportBatch>(`imports/${id}/${what}/`),
    onSuccess: (b) => {
      qc.setQueryData(["import", id], b);
      qc.invalidateQueries({ queryKey: ["imports"] });
      qc.invalidateQueries({ queryKey: ["orders"] });
      qc.invalidateQueries({ queryKey: ["summary"] });
      message.success(b.status === "committed" ? t("imports.committed") : t("common.saved"));
    },
    onError: (e) => message.error(error(e)),
  });

  const b = batch.data;
  if (!b) return <Card loading />;
  const orders = b.preview.orders ?? [];
  const importable = b.kind === "orders" ? (b.preview.importable ?? 0) : Object.entries(b.preview.actions ?? {}).filter(([k]) => k !== "unchanged").reduce((s, [, v]) => s + v, 0);

  return (
    <>
      <div className="oc-page-header">
        <Space wrap>
          <Button icon={dir === "rtl" ? <ArrowRightOutlined /> : <ArrowLeftOutlined />} onClick={() => nav(`/imports?kind=${b.kind}`)} />
          <h2><Ltr>{b.file_name}</Ltr></h2>
          <Tag color={IMPORT_STATUS_COLOR[b.status]}>{t(`imports.status.${b.status}`)}</Tag>
          <Typography.Text type="secondary">{b.uploaded_by_name} · {dateTime(b.uploaded_at)}</Typography.Text>
        </Space>
        {b.status === "validated" && (
          <Space>
            <Button icon={<DeleteOutlined />} onClick={() => act.mutate("discard")} loading={act.isPending && act.variables === "discard"}>{t("imports.discard")}</Button>
            <Popconfirm title={t("imports.commitConfirm")} okText={t("common.yes")} cancelText={t("common.no")} onConfirm={() => act.mutate("commit")} disabled={!importable}>
              <Button type="primary" icon={<CheckOutlined />} disabled={!importable} loading={act.isPending && act.variables === "commit"}>
                {t("imports.commit")} ({num(importable)})
              </Button>
            </Popconfirm>
          </Space>
        )}
      </div>

      {b.file_errors.length > 0 && <Alert type="error" showIcon style={{ marginBottom: 16 }} message={<ProblemList items={b.file_errors} type="error" />} />}

      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col flex="1 1 140px"><Card size="small"><Statistic title={t("imports.rows")} value={num(b.rows_total)} /></Card></Col>
        <Col flex="1 1 140px"><Card size="small"><Statistic title={t("imports.errors")} value={num(b.rows_error)} valueStyle={{ color: b.rows_error ? "#dc2626" : undefined }} /></Card></Col>
        <Col flex="1 1 140px"><Card size="small"><Statistic title={t("imports.warnings")} value={num(b.rows_warning)} valueStyle={{ color: b.rows_warning ? "#d97706" : undefined }} /></Card></Col>
        {b.kind === "orders" ? (
          <Col flex="1 1 140px"><Card size="small"><Statistic title={t("imports.importable")} value={`${num(b.preview.importable ?? 0)} / ${num(orders.length)}`} /></Card></Col>
        ) : (
          Object.entries(b.preview.actions ?? {}).map(([k, v]) => (
            <Col flex="1 1 140px" key={k}><Card size="small"><Statistic title={t(`imports.mapping.${k}`, k)} value={num(v)} /></Card></Col>
          ))
        )}
      </Row>

      {b.status === "committed" && <CommitResult batch={b} />}

      {b.kind === "orders" && orders.length > 0 && (
        <Card size="small" title={t("imports.preview")} style={{ marginBottom: 16 }}>
          <Table<ImportOrderPreview>
            rowKey="key" size="small" dataSource={orders} pagination={false} scroll={{ x: 900 }}
            columns={[
              { title: t("order.reference"), dataIndex: "reference_id", render: (v, r) => (r.existing_order_id ? <a onClick={() => nav(`/orders/${r.existing_order_id}`)}><Ltr>{v}</Ltr></a> : <Ltr>{v}</Ltr>) },
              { title: t("order.customer"), dataIndex: "customer" },
              { title: t("order.created"), dataIndex: "created_at", render: (v) => dateTime(v) },
              { title: t("order.picker"), dataIndex: "picker", render: (v) => v || t("common.none") },
              { title: t("order.lines"), dataIndex: "lines", render: (v) => num(v) },
              { title: t("order.boxes"), dataIndex: "boxes", render: (v) => num(v) },
              { title: t("common.units"), dataIndex: "units", render: (v) => num(v) },
              { title: t("imports.errors"), dataIndex: "error_rows", render: (v) => (v ? <Typography.Text type="danger">{num(v)}</Typography.Text> : num(0)) },
              { title: t("imports.warnings"), dataIndex: "warning_rows", render: (v) => (v ? <Typography.Text type="warning">{num(v)}</Typography.Text> : num(0)) },
              {
                title: t("common.status"), dataIndex: "action",
                render: (a: string, r) => (
                  <Space size={4}>
                    <Tag color={ACTION_COLOR[a]}>{t(`imports.action.${a}`, a)}</Tag>
                    {r.existing_status && <Tag>{t(`status.${r.existing_status}`)}</Tag>}
                    {b.status === "validated" && APPLIED.has(a) && <CheckOutlined style={{ color: "#16a34a" }} />}
                  </Space>
                ),
              },
            ]}
          />
        </Card>
      )}

      {(b.rows_error > 0 || b.rows_warning > 0) && <ProblemRows batch={b} />}
    </>
  );
}

function CommitResult({ batch }: { batch: ImportBatch }) {
  const { t, num, dateTime } = useI18n();
  const r = batch.result as { orders?: Record<string, string[]>; mapping_conflicts?: { barcode: string; file_product_id: string; mapped_product_id: string }[]; actions?: Record<string, number> };
  return (
    <Alert
      type="success" showIcon style={{ marginBottom: 16 }}
      message={`${t("imports.committed")} · ${dateTime(batch.committed_at)}`}
      description={
        <>
          {r.orders && Object.entries(r.orders).map(([k, refs]) => (
            <div key={k}><Tag color={ACTION_COLOR[k]}>{t(`imports.action.${k}`, k)}</Tag> {refs.map((x) => <Ltr key={x}>{x} </Ltr>)}</div>
          ))}
          {r.actions && Object.entries(r.actions).map(([k, v]) => <Tag key={k}>{t(`imports.mapping.${k}`, k)}: {num(v)}</Tag>)}
          {!!r.mapping_conflicts?.length && (
            <div style={{ marginTop: 8 }}>
              {t("imports.resultConflicts")}:{" "}
              {r.mapping_conflicts.map((c) => <Tag key={c.barcode}><Ltr>{c.barcode}: {c.file_product_id} → {c.mapped_product_id}</Ltr></Tag>)}
            </div>
          )}
        </>
      }
    />
  );
}

function ProblemRows({ batch }: { batch: ImportBatch }) {
  const { t, num } = useI18n();
  const [filter, setFilter] = useState<"problems" | "errors" | "warnings">(batch.rows_error ? "errors" : "warnings");
  const [page, setPage] = useState(1);
  const rows = useQuery({
    queryKey: ["import-rows", batch.id, filter, page],
    queryFn: () => get<Page<ImportRow>>(`imports/${batch.id}/rows/?filter=${filter}&limit=50&offset=${(page - 1) * 50}`),
  });
  return (
    <Card size="small" title={t("imports.problemRows")}
      extra={<Segmented size="small" value={filter} onChange={(v) => { setFilter(v as typeof filter); setPage(1); }}
        options={[{ label: t("imports.errors"), value: "errors" }, { label: t("imports.warnings"), value: "warnings" }, { label: t("common.all"), value: "problems" }]} />}>
      <Table<ImportRow>
        rowKey="row_no" size="small" loading={rows.isLoading} dataSource={rows.data?.results ?? []} scroll={{ x: 900 }}
        pagination={{ current: page, pageSize: 50, total: rows.data?.count ?? 0, onChange: setPage, showSizeChanger: false }}
        columns={[
          { title: t("imports.row"), dataIndex: "row_no", width: 70, render: (v) => num(v) },
          ...(batch.kind === "orders" ? [{ title: t("order.reference"), render: (_: unknown, r: ImportRow) => <Ltr>{String(r.raw.reference_id ?? "")}</Ltr> }] : []),
          { title: t("line.productId"), width: 110, render: (_, r) => <Ltr>{String(r.raw.product_id ?? "")}</Ltr> },
          { title: t("line.product"), width: 240, render: (_, r) => String(r.raw.title ?? "") },
          {
            title: `${t("imports.errors")} / ${t("imports.warnings")}`, width: 460,
            render: (_, r) => <><ProblemList items={r.errors} type="error" /><ProblemList items={r.warnings} type="warning" /></>,
          },
        ]}
      />
    </Card>
  );
}
