import { UploadOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Checkbox, Drawer, Form, Input, Popconfirm, Space, Table, Tag } from "antd";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { get, post, qs, type Page } from "../api/client";
import type { BarcodeRow, ProductDetail, ProductRow } from "../api/types";
import { useAuth } from "../auth";
import { Ltr } from "../components/common";
import { useI18n } from "../i18n";

export default function BarcodesPage() {
  const { t, num } = useI18n();
  const { can } = useAuth();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [productId, setProductId] = useState<string | null>(null);
  const list = useQuery({
    queryKey: ["products", q, page],
    queryFn: () => get<Page<ProductRow>>(`products/${qs({ q, limit: 50, offset: (page - 1) * 50 })}`),
  });

  return (
    <>
      <div className="oc-page-header">
        <h2>{t("menu.barcodes")}</h2>
        {can("barcodes.manage") && <Button icon={<UploadOutlined />} onClick={() => nav("/imports?kind=barcodes")}>{t("imports.barcodesTab")}</Button>}
      </div>
      <div className="oc-toolbar">
        <Input.Search allowClear placeholder={t("barcodes.searchHint")} style={{ width: 340 }} onSearch={(v) => { setQ(v.trim()); setPage(1); }} />
      </div>
      <Table<ProductRow>
        rowKey="id" size="small" loading={list.isLoading} dataSource={list.data?.results ?? []}
        onRow={(r) => ({ onClick: () => setProductId(r.id), style: { cursor: "pointer" } })}
        pagination={{ current: page, pageSize: 50, total: list.data?.count ?? 0, onChange: setPage, showSizeChanger: false, showTotal: (n) => `${t("common.total")}: ${num(n)}` }}
        columns={[
          { title: t("line.productId"), dataIndex: "id", width: 140, render: (v) => <Ltr>{v}</Ltr> },
          { title: t("line.product"), dataIndex: "title" },
        ]}
      />
      <ProductDrawer productId={productId} onClose={() => setProductId(null)} />
    </>
  );
}

/** Canonical GTIN-14 keys are zero-padded; show the familiar 13-digit form. */
function displayCode(code: string) {
  return code.length === 14 && code.startsWith("0") ? code.slice(1) : code;
}

function ProductDrawer({ productId, onClose }: { productId: string | null; onClose: () => void }) {
  const { t, dateTime, error } = useI18n();
  const { can } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [form] = Form.useForm<{ barcode: string; replace: boolean }>();
  const p = useQuery({ queryKey: ["product", productId], queryFn: () => get<ProductDetail>(`products/${productId}/`), enabled: !!productId });
  const refresh = () => qc.invalidateQueries({ queryKey: ["product", productId] });

  const add = useMutation({
    mutationFn: (v: { barcode: string; replace: boolean }) => post(`products/${productId}/barcodes/`, v),
    onSuccess: () => { message.success(t("common.saved")); form.resetFields(); refresh(); },
    onError: (e) => message.error(error(e)),
  });
  const deactivate = useMutation({
    mutationFn: (id: number) => post(`products/barcodes/${id}/deactivate/`),
    onSuccess: () => { message.success(t("common.saved")); refresh(); },
    onError: (e) => message.error(error(e)),
  });

  return (
    <Drawer open={!!productId} onClose={onClose} width={680} title={p.data ? <>{p.data.title} · <Ltr>{p.data.id}</Ltr></> : t("common.loading")}>
      {can("barcodes.manage") && (
        <Form form={form} layout="inline" onFinish={(v) => add.mutate(v)} style={{ marginBottom: 16, rowGap: 8 }}>
          <Form.Item name="barcode" rules={[{ required: true }]}><Input dir="ltr" placeholder={t("line.barcode")} style={{ width: 200 }} /></Form.Item>
          <Form.Item name="replace" valuePropName="checked" initialValue={false}><Checkbox>{t("barcodes.replace")}</Checkbox></Form.Item>
          <Button type="primary" htmlType="submit" loading={add.isPending}>{t("barcodes.add")}</Button>
        </Form>
      )}
      <Table<BarcodeRow>
        rowKey="id" size="small" loading={p.isLoading} dataSource={p.data?.barcodes ?? []} pagination={false}
        columns={[
          {
            title: t("line.barcode"), dataIndex: "barcode",
            render: (v, r) => r.is_derived
              ? <Space wrap><Ltr copy>{displayCode(r.code)}</Ltr><Tag color="gold">{t("barcodes.derived")} ← <Ltr>{v}</Ltr></Tag></Space>
              : <Ltr copy>{v}</Ltr>,
          },
          { title: t("barcodes.source"), dataIndex: "source", render: (v) => t(`barcodes.sources.${v}`, v) },
          { title: t("common.status"), dataIndex: "is_active", render: (v) => <Tag color={v ? "green" : "default"}>{v ? t("common.active") : t("common.inactive")}</Tag> },
          { title: t("barcodes.created"), dataIndex: "created_at", render: (v) => dateTime(v) },
          { title: t("barcodes.deactivated"), dataIndex: "deactivated_at", render: (v) => dateTime(v) },
          ...(can("barcodes.manage") ? [{
            title: "", render: (_: unknown, r: BarcodeRow) => r.is_active && (
              <Popconfirm title={t("barcodes.deactivateConfirm")} okText={t("common.yes")} cancelText={t("common.no")} onConfirm={() => deactivate.mutate(r.id)}>
                <Button size="small" danger>{t("barcodes.deactivate")}</Button>
              </Popconfirm>
            ),
          }] : []),
        ]}
      />
    </Drawer>
  );
}
