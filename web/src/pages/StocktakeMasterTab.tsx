import { DeleteOutlined, DownloadOutlined, EditOutlined, InboxOutlined, PlusOutlined, UploadOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Col, Descriptions, Form, Input, Modal, Popconfirm, Radio, Row, Select, Space, Statistic, Switch, Table, Tag, Typography, Upload } from "antd";
import { useState } from "react";
import { del, download, get, patch, post, qs, type Page } from "../api/client";
import type { MasterImportResult, MasterItem, MasterStats } from "../api/types";
import { Ltr } from "../components/common";
import { useI18n } from "../i18n";

const SOURCE_COLOR: Record<MasterItem["source"], string> = { import: "blue", manual: "green", counter: "orange" };

/** Stocktaking product list (barcode -> title). Separate from the order-checking barcode mapping. */
export default function StocktakeMasterTab() {
  const { t, num, dateTime, error } = useI18n();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [source, setSource] = useState<string | undefined>();
  const [multi, setMulti] = useState(false);
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Partial<MasterItem> | null>(null);
  const [importing, setImporting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form] = Form.useForm();
  const query = qs({ q, source, multi: multi || undefined, page });
  const list = useQuery({ queryKey: ["master", query], queryFn: () => get<Page<MasterItem>>(`stocktake-master/${query}`) });
  const stats = useQuery({ queryKey: ["master", "stats"], queryFn: () => get<MasterStats>("stocktake-master/stats/") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["master"] });

  const save = useMutation({
    mutationFn: (v: Partial<MasterItem>) => (editing?.id ? patch(`stocktake-master/${editing.id}/`, v) : post("stocktake-master/", v)),
    onSuccess: () => { message.success(t("common.saved")); setEditing(null); refresh(); },
    onError: (e) => message.error(error(e)),
  });
  const remove = useMutation({
    mutationFn: (id: number) => del(`stocktake-master/${id}/`),
    onSuccess: refresh,
    onError: (e) => message.error(error(e)),
  });
  const open = (m: Partial<MasterItem>) => { setEditing(m); form.setFieldsValue({ barcode: m.barcode ?? "", title: m.title ?? "" }); };
  const exportAll = async () => {
    setBusy(true);
    try { await download("stocktake-master/export/", "stocktake_master.xlsx"); } catch (e) { message.error(error(e)); } finally { setBusy(false); }
  };
  const s = stats.data;

  return (
    <>
      <Typography.Paragraph type="secondary">{t("master.hint")}</Typography.Paragraph>
      {s && (
        <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
          <Col flex="1 1 150px"><Card size="small"><Statistic title={t("master.items")} value={num(s.items)} /></Card></Col>
          <Col flex="1 1 150px"><Card size="small"><Statistic title={t("master.barcodes")} value={num(s.barcodes)} /></Card></Col>
          <Col flex="1 1 150px"><Card size="small"><Statistic title={t("master.multiTitle")} value={num(s.multi_title_barcodes)} /></Card></Col>
          <Col flex="1 1 150px"><Card size="small" style={{ cursor: "pointer" }} onClick={() => { setSource("counter"); setPage(1); }}>
            <Statistic title={t("master.source.counter")} value={num(s.by_source.counter ?? 0)} valueStyle={{ color: "#c2410c" }} /></Card></Col>
        </Row>
      )}
      <div className="oc-toolbar">
        <Button type="primary" icon={<UploadOutlined />} onClick={() => setImporting(true)}>{t("master.import")}</Button>
        <Button icon={<PlusOutlined />} onClick={() => open({})}>{t("master.add")}</Button>
        <Button icon={<DownloadOutlined />} loading={busy} onClick={exportAll}>{t("master.export")}</Button>
        <Input.Search allowClear placeholder={t("master.search")} style={{ width: 260 }} onSearch={(v) => { setQ(v); setPage(1); }} />
        <Select allowClear placeholder={t("master.sourceLabel")} style={{ width: 170 }} value={source} onChange={(v) => { setSource(v); setPage(1); }}
          options={(["import", "manual", "counter"] as const).map((k) => ({ value: k, label: t(`master.source.${k}`) }))} />
        <Space><Switch checked={multi} onChange={(v) => { setMulti(v); setPage(1); }} /> {t("master.onlyMulti")}</Space>
      </div>
      <Table<MasterItem>
        className="oc-nowrap" rowKey="id" size="small" loading={list.isLoading} dataSource={list.data?.results ?? []}
        tableLayout="auto" scroll={{ x: "max-content" }}
        pagination={{ current: page, pageSize: 50, total: list.data?.count, onChange: setPage, showSizeChanger: false,
          showTotal: (n) => `${t("common.total")}: ${num(n)}` }}
        columns={[
          { title: t("master.barcode"), dataIndex: "barcode", render: (v) => <Ltr>{v}</Ltr> },
          { title: t("master.title"), dataIndex: "title", render: (v) => <span className="oc-clip" style={{ maxWidth: 420 }} title={v}>{v}</span> },
          { title: t("master.sourceLabel"), dataIndex: "source", render: (v: MasterItem["source"]) => <Tag color={SOURCE_COLOR[v]}>{t(`master.source.${v}`)}</Tag> },
          { title: t("master.by"), dataIndex: "created_by", render: (v) => v ?? t("common.none") },
          { title: t("master.updated"), dataIndex: "updated_at", render: dateTime },
          {
            title: "", render: (_, m) => (
              <Space>
                <Button size="small" icon={<EditOutlined />} onClick={() => open(m)} />
                <Popconfirm title={t("master.deleteConfirm")} onConfirm={() => remove.mutate(m.id)}>
                  <Button size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />
      <Modal open={editing !== null} title={editing?.id ? t("common.edit") : t("master.add")} onCancel={() => setEditing(null)}
        onOk={() => form.submit()} okText={t("common.save")} cancelText={t("common.cancel")} confirmLoading={save.isPending} destroyOnHidden>
        <Form form={form} layout="vertical" onFinish={(v) => save.mutate(v)}>
          <Form.Item name="barcode" label={t("master.barcode")} rules={[{ required: true, whitespace: true }]}><Input dir="ltr" /></Form.Item>
          <Form.Item name="title" label={t("master.title")} rules={[{ required: true, whitespace: true }]}><Input /></Form.Item>
        </Form>
      </Modal>
      <ImportModal open={importing} onClose={() => setImporting(false)} onDone={refresh} />
    </>
  );
}

function ImportModal({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const { t, num, error } = useI18n();
  const { message } = App.useApp();
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<"merge" | "replace">("merge");
  const [preview, setPreview] = useState<MasterImportResult | null>(null);
  const [busy, setBusy] = useState(false);

  const send = async (dryRun: boolean) => {
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("mode", mode);
      fd.append("dry_run", String(dryRun));
      const r = await post<MasterImportResult>("stocktake-master/import/", fd);
      if (dryRun) setPreview(r);
      else { message.success(t("master.imported")); onDone(); close(); }
    } catch (e) { message.error(error(e)); } finally { setBusy(false); }
  };
  const close = () => { setFile(null); setPreview(null); setMode("merge"); onClose(); };

  return (
    <Modal open={open} title={t("master.import")} onCancel={close} width={640} destroyOnHidden
      footer={[
        <Button key="c" onClick={close}>{t("common.cancel")}</Button>,
        preview
          ? <Button key="i" type="primary" danger={mode === "replace" && preview.removed > 0} loading={busy} onClick={() => send(false)}>{t("master.apply")}</Button>
          : <Button key="p" type="primary" disabled={!file} loading={busy} onClick={() => send(true)}>{t("master.preview")}</Button>,
      ]}>
      <Upload.Dragger accept=".csv,.xlsx,.txt" multiple={false} showUploadList={false} disabled={busy}
        beforeUpload={(f) => { setFile(f); setPreview(null); return false; }}>
        <p className="ant-upload-drag-icon"><InboxOutlined /></p>
        <p className="ant-upload-text">{file ? file.name : t("master.dragHint")}</p>
        <p className="ant-upload-hint">{t("master.columnsHint")}</p>
      </Upload.Dragger>
      <Radio.Group style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 8 }} value={mode}
        onChange={(e) => { setMode(e.target.value); setPreview(null); }}>
        <Radio value="merge"><b>{t("master.merge")}</b> — {t("master.mergeHint")}</Radio>
        <Radio value="replace"><b>{t("master.replace")}</b> — {t("master.replaceHint")}</Radio>
      </Radio.Group>
      {preview && (
        <>
          <Descriptions size="small" bordered column={2} style={{ marginTop: 16 }}>
            <Descriptions.Item label={t("master.rows")}>{num(preview.rows)}</Descriptions.Item>
            <Descriptions.Item label={t("master.items")}>{num(preview.items)}</Descriptions.Item>
            <Descriptions.Item label={t("master.new")}><b>{num(preview.new)}</b></Descriptions.Item>
            <Descriptions.Item label={t("master.updatedN")}>{num(preview.updated)}</Descriptions.Item>
            <Descriptions.Item label={t("master.unchanged")}>{num(preview.unchanged)}</Descriptions.Item>
            <Descriptions.Item label={t("master.removed")}><Typography.Text type={preview.removed ? "danger" : undefined}>{num(preview.removed)}</Typography.Text></Descriptions.Item>
            <Descriptions.Item label={t("master.multiTitle")}>{num(preview.barcodes_with_several_titles)}</Descriptions.Item>
            <Descriptions.Item label={t("master.duplicateRows")}>{num(preview.duplicate_rows)}</Descriptions.Item>
          </Descriptions>
          {preview.errors > 0 && (
            <Alert type="warning" showIcon style={{ marginTop: 12 }} message={t("master.errorRows").replace("{n}", num(preview.errors))}
              description={preview.error_rows.slice(0, 8).map((e) => `${t("master.row")} ${num(e.row)}: ${t(`master.errors.${e.code}`, e.code)}`).join(" · ")} />
          )}
        </>
      )}
    </Modal>
  );
}
