import { InboxOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { App, Card, Table, Tabs, Tag, Typography, Upload } from "antd";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { get, post, type Page } from "../api/client";
import type { ImportBatch } from "../api/types";
import { useAuth } from "../auth";
import { Ltr } from "../components/common";
import { useI18n } from "../i18n";

const ORDER_COLUMNS = "reference_id, reference_type, customer, product_id, title, pack_ordered, inc_ordered, units_ordered, barcode1…barcodeN";

export const IMPORT_STATUS_COLOR: Record<ImportBatch["status"], string> = { validated: "gold", committed: "green", discarded: "default", failed: "red" };

export default function ImportsPage() {
  const { t } = useI18n();
  const { can } = useAuth();
  const [sp, setSp] = useSearchParams();
  const kinds = [can("orders.import") && "orders", can("barcodes.manage") && "barcodes"].filter(Boolean) as ("orders" | "barcodes")[];
  const kind = (sp.get("kind") as "orders" | "barcodes") || kinds[0];

  return (
    <>
      <div className="oc-page-header"><h2>{t("imports.title")}</h2></div>
      <Tabs
        activeKey={kind}
        onChange={(k) => setSp({ kind: k }, { replace: true })}
        items={kinds.map((k) => ({
          key: k,
          label: k === "orders" ? t("imports.ordersTab") : t("imports.barcodesTab"),
          children: <KindPanel kind={k} />,
        }))}
      />
    </>
  );
}

function KindPanel({ kind }: { kind: "orders" | "barcodes" }) {
  const { t, num, dateTime, error } = useI18n();
  const { message } = App.useApp();
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);
  const [page, setPage] = useState(1);
  const history = useQuery({
    queryKey: ["imports", kind, page],
    queryFn: () => get<Page<ImportBatch>>(`imports/?kind=${kind}&limit=20&offset=${(page - 1) * 20}`),
  });

  const upload = async (file: File) => {
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("kind", kind);
      fd.append("file", file);
      const b = await post<ImportBatch>("imports/", fd);
      nav(`/imports/${b.id}`);
    } catch (e) {
      message.error(error(e));
    } finally {
      setBusy(false);
    }
    return false;
  };

  return (
    <>
      <Card size="small" style={{ marginBottom: 16 }}>
        <Upload.Dragger accept=".xlsx,.xlsm" multiple={false} showUploadList={false} disabled={busy} beforeUpload={(f) => { void upload(f); return false; }}>
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">{busy ? t("common.loading") : t("imports.dragHint")}</p>
          <p className="ant-upload-hint">
            {kind === "orders" ? <>{t("imports.templateHint")} <Ltr>{ORDER_COLUMNS}</Ltr></> : t("imports.mappingHint")}
          </p>
        </Upload.Dragger>
      </Card>

      <Typography.Title level={5}>{t("imports.history")}</Typography.Title>
      <Table<ImportBatch>
        rowKey="id" size="small" loading={history.isLoading} dataSource={history.data?.results ?? []} scroll={{ x: 800 }}
        onRow={(r) => ({ onClick: () => nav(`/imports/${r.id}`), style: { cursor: "pointer" } })}
        pagination={{ current: page, pageSize: 20, total: history.data?.count ?? 0, onChange: setPage, showSizeChanger: false }}
        columns={[
          { title: "#", dataIndex: "id", render: (v) => num(v) },
          { title: t("imports.file"), dataIndex: "file_name", render: (v) => <Ltr>{v}</Ltr> },
          { title: t("common.status"), dataIndex: "status", render: (s: ImportBatch["status"]) => <Tag color={IMPORT_STATUS_COLOR[s]}>{t(`imports.status.${s}`)}</Tag> },
          { title: t("imports.rows"), dataIndex: "rows_total", render: (v) => num(v) },
          { title: t("imports.errors"), dataIndex: "rows_error", render: (v) => (v ? <Typography.Text type="danger">{num(v)}</Typography.Text> : num(0)) },
          { title: t("imports.warnings"), dataIndex: "rows_warning", render: (v) => (v ? <Typography.Text type="warning">{num(v)}</Typography.Text> : num(0)) },
          { title: t("imports.uploadedBy"), dataIndex: "uploaded_by_name" },
          { title: t("imports.uploadedAt"), dataIndex: "uploaded_at", render: (v) => dateTime(v) },
        ]}
      />
    </>
  );
}
