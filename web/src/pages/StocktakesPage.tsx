import { PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Form, Input, Modal, Select, Space, Switch, Table, Tag } from "antd";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { get, patch, post, qs, type Page } from "../api/client";
import type { StocktakeBrief, Stocktaker, Vendor } from "../api/types";
import { DateRange, DateSingle } from "../components/DateRange";
import { Ltr } from "../components/common";
import StocktakeMasterTab from "./StocktakeMasterTab";
import { useI18n } from "../i18n";

export const useVendors = (activeOnly = false) =>
  useQuery({ queryKey: ["vendors", activeOnly], queryFn: () => get<Vendor[]>(`vendors/${activeOnly ? "?active=true" : ""}`), staleTime: 30_000 });
export const useStocktakers = () => useQuery({ queryKey: ["stocktakers"], queryFn: () => get<Stocktaker[]>("stocktakers/"), staleTime: 30_000 });

export function StatusTag({ status }: { status: StocktakeBrief["status"] }) {
  const { t } = useI18n();
  return <Tag color={status === "open" ? "processing" : "default"}>{t(`stocktake.status.${status}`)}</Tag>;
}

/** Stocktaking section pages: stocktakes, product list, vendors (each its own menu item). */
export default function StocktakesPage({ view = "list" }: { view?: "list" | "master" | "vendors" }) {
  const { t } = useI18n();
  const title = { list: t("menu.stocktakeList"), master: t("menu.master"), vendors: t("menu.vendors") }[view];
  return (
    <>
      <div className="oc-page-header"><h2>{title}</h2></div>
      {view === "list" ? <StocktakeList /> : view === "master" ? <StocktakeMasterTab /> : <Vendors />}
    </>
  );
}

function StocktakeList() {
  const { t, num, date } = useI18n();
  const nav = useNavigate();
  const [range, setRange] = useState<[string, string] | null>(null);
  const [vendor, setVendor] = useState<number | undefined>();
  const [status, setStatus] = useState<string | undefined>();
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const vendors = useVendors();
  const query = qs({ from: range?.[0], to: range?.[1], vendor, status, page });
  const list = useQuery({ queryKey: ["stocktakes", query], queryFn: () => get<Page<StocktakeBrief>>(`stocktakes/${query}`), refetchInterval: 15_000 });

  return (
    <>
      <div className="oc-toolbar">
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>{t("stocktake.new")}</Button>
        <DateRange value={range} onChange={(v) => { setRange(v); setPage(1); }} />
        <Select allowClear showSearch optionFilterProp="label" placeholder={t("stocktake.allVendors")} style={{ width: 220 }}
          value={vendor} onChange={(v) => { setVendor(v); setPage(1); }}
          options={(vendors.data ?? []).map((v) => ({ value: v.id, label: v.name }))} />
        <Select allowClear placeholder={t("common.status")} style={{ width: 140 }} value={status} onChange={(v) => { setStatus(v); setPage(1); }}
          options={(["open", "closed"] as const).map((s) => ({ value: s, label: t(`stocktake.status.${s}`) }))} />
      </div>
      <Table<StocktakeBrief>
        className="oc-nowrap" rowKey="id" size="middle" loading={list.isLoading} dataSource={list.data?.results ?? []}
        tableLayout="auto" scroll={{ x: "max-content" }}
        onRow={(r) => ({ onClick: () => nav(`/stocktaking/${r.id}`), style: { cursor: "pointer" } })}
        pagination={{ current: page, pageSize: 50, total: list.data?.count, onChange: setPage, showSizeChanger: false,
          showTotal: (n) => `${t("common.total")}: ${num(n)}` }}
        columns={[
          { title: t("stocktake.date"), dataIndex: "date", render: (v) => date(v + "T12:00:00") },
          { title: t("stocktake.vendor"), render: (_, r) => <b>{r.vendor.name}</b> },
          { title: t("stocktake.counters"), render: (_, r) => <Space size={[0, 4]} wrap>{r.counters.map((c) => <Tag key={c.id}>{c.name}</Tag>)}</Space> },
          { title: t("common.status"), dataIndex: "status", render: (s) => <StatusTag status={s} /> },
          { title: t("stocktake.records"), dataIndex: "records", render: (v) => num(v ?? 0) },
          { title: t("stocktake.barcodes"), dataIndex: "barcodes", render: (v) => num(v ?? 0) },
          { title: t("stocktake.quantity"), dataIndex: "quantity", render: (v) => <b>{num(v ?? 0)}</b> },
          { title: t("stocktake.note"), dataIndex: "note", render: (v) => <span className="oc-clip" title={v}>{v}</span> },
        ]}
      />
      <StocktakeForm open={creating} onClose={() => setCreating(false)} onSaved={(s) => nav(`/stocktaking/${s.id}`)} />
    </>
  );
}

/** Create, or edit (vendor/date/counters/note) an open stocktake. */
export function StocktakeForm({ open, onClose, onSaved, initial }: {
  open: boolean; onClose: () => void; onSaved?: (s: StocktakeBrief) => void; initial?: StocktakeBrief;
}) {
  const { t, error } = useI18n();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [form] = Form.useForm();
  const vendors = useVendors(true);
  const counters = useStocktakers();
  const [newVendor, setNewVendor] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (v: Record<string, unknown>) => (initial ? patch<StocktakeBrief>(`stocktakes/${initial.id}/`, v) : post<StocktakeBrief>("stocktakes/", v)),
    onSuccess: (s) => {
      message.success(t("common.saved"));
      qc.invalidateQueries({ queryKey: ["stocktakes"] });
      qc.invalidateQueries({ queryKey: ["stocktake"] });
      onClose();
      onSaved?.(s);
    },
    onError: (e) => message.error(error(e)),
  });
  const addVendor = useMutation({
    mutationFn: (name: string) => post<Vendor>("vendors/", { name }),
    onSuccess: (v) => { qc.invalidateQueries({ queryKey: ["vendors"] }); form.setFieldValue("vendor_id", v.id); setNewVendor(null); },
    onError: (e) => message.error(error(e)),
  });

  return (
    <Modal open={open} title={initial ? t("common.edit") : t("stocktake.new")} onCancel={onClose} onOk={() => form.submit()}
      okText={t("common.save")} cancelText={t("common.cancel")} confirmLoading={save.isPending} destroyOnHidden
      afterOpenChange={(o) => o && form.setFieldsValue(initial
        ? { vendor_id: initial.vendor.id, date: initial.date, counter_ids: initial.counters.map((c) => c.id), note: initial.note }
        : { vendor_id: undefined, date: new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Tehran" }), counter_ids: [], note: "" })}>
      {counters.data && counters.data.length === 0 && <Alert type="warning" showIcon style={{ marginBottom: 12 }} message={t("stocktake.noCounters")} />}
      <Form form={form} layout="vertical" onFinish={(v) => save.mutate(v)}>
        <Form.Item label={t("stocktake.vendor")} required>
          <Space.Compact style={{ width: "100%" }}>
            <Form.Item name="vendor_id" noStyle rules={[{ required: true }]}>
              <Select showSearch optionFilterProp="label" style={{ width: "100%" }}
                options={(vendors.data ?? []).map((v) => ({ value: v.id, label: v.name }))} />
            </Form.Item>
            <Button icon={<PlusOutlined />} onClick={() => setNewVendor("")}>{t("stocktake.newVendor")}</Button>
          </Space.Compact>
        </Form.Item>
        {newVendor !== null && (
          <Space.Compact style={{ width: "100%", marginBottom: 16 }}>
            <Input autoFocus placeholder={t("stocktake.vendorName")} value={newVendor} onChange={(e) => setNewVendor(e.target.value)}
              onPressEnter={(e) => { e.preventDefault(); if (newVendor.trim()) addVendor.mutate(newVendor.trim()); }} />
            <Button type="primary" loading={addVendor.isPending} disabled={!newVendor.trim()} onClick={() => addVendor.mutate(newVendor.trim())}>{t("common.add")}</Button>
            <Button onClick={() => setNewVendor(null)}>{t("common.cancel")}</Button>
          </Space.Compact>
        )}
        <Form.Item name="date" label={t("stocktake.date")} rules={[{ required: true }]}><DateSingle /></Form.Item>
        <Form.Item name="counter_ids" label={t("stocktake.counters")} rules={[{ required: true, type: "array", min: 1 }]}>
          <Select mode="multiple" showSearch optionFilterProp="label"
            options={(counters.data ?? []).map((c) => ({ value: c.id, label: `${c.name}${c.open_stocktakes ? ` (${c.open_stocktakes})` : ""}` }))} />
        </Form.Item>
        <Form.Item name="note" label={t("stocktake.note")}><Input.TextArea rows={2} maxLength={500} /></Form.Item>
      </Form>
    </Modal>
  );
}

function Vendors() {
  const { t, num, error } = useI18n();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const vendors = useVendors();
  const [editing, setEditing] = useState<Partial<Vendor> | null>(null);
  const [form] = Form.useForm<Partial<Vendor>>();
  const save = useMutation({
    mutationFn: (v: Partial<Vendor>) => (editing?.id ? patch(`vendors/${editing.id}/`, v) : post("vendors/", v)),
    onSuccess: () => { message.success(t("common.saved")); setEditing(null); qc.invalidateQueries({ queryKey: ["vendors"] }); },
    onError: (e) => message.error(error(e)),
  });
  const toggle = useMutation({
    mutationFn: (v: Vendor) => patch(`vendors/${v.id}/`, { is_active: !v.is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["vendors"] }),
    onError: (e) => message.error(error(e)),
  });
  const open = (v: Partial<Vendor>) => { setEditing(v); form.setFieldsValue({ name: v.name ?? "", code: v.code ?? "" }); };

  return (
    <>
      <div className="oc-toolbar">
        <Button type="primary" icon={<PlusOutlined />} onClick={() => open({})}>{t("stocktake.newVendor")}</Button>
      </div>
      <Table<Vendor>
        rowKey="id" size="middle" loading={vendors.isLoading} dataSource={vendors.data ?? []} pagination={false}
        columns={[
          { title: t("stocktake.vendorName"), dataIndex: "name", render: (v) => <b>{v}</b> },
          { title: t("stocktake.vendorCode"), dataIndex: "code", render: (v) => (v ? <Ltr>{v}</Ltr> : t("common.none")) },
          { title: t("stocktake.list"), dataIndex: "stocktakes_count", render: (v) => num(v ?? 0) },
          { title: t("common.active"), dataIndex: "is_active", render: (v, r) => <Switch checked={v} loading={toggle.isPending && toggle.variables?.id === r.id} onChange={() => toggle.mutate(r)} /> },
          { title: "", render: (_, r) => <Button size="small" onClick={() => open(r)}>{t("common.edit")}</Button> },
        ]}
      />
      <Modal open={editing !== null} title={editing?.id ? t("common.edit") : t("stocktake.newVendor")} onCancel={() => setEditing(null)}
        onOk={() => form.submit()} okText={t("common.save")} cancelText={t("common.cancel")} confirmLoading={save.isPending} destroyOnHidden>
        <Form form={form} layout="vertical" onFinish={(v) => save.mutate(v)}>
          <Form.Item name="name" label={t("stocktake.vendorName")} rules={[{ required: true, whitespace: true }]}><Input /></Form.Item>
          <Form.Item name="code" label={t("stocktake.vendorCode")}><Input dir="ltr" /></Form.Item>
        </Form>
      </Modal>
    </>
  );
}
