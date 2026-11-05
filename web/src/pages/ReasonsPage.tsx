import { PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Form, Input, InputNumber, Modal, Select, Switch, Table, Tag } from "antd";
import { useState } from "react";
import { get, patch, post, type Page } from "../api/client";
import type { Reason } from "../api/types";
import { useAuth } from "../auth";
import { Ltr } from "../components/common";
import { useI18n } from "../i18n";

export default function ReasonsPage() {
  const { t, num, error } = useI18n();
  const { can } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [editing, setEditing] = useState<Partial<Reason> | null>(null);
  const [form] = Form.useForm<Partial<Reason>>();
  const editable = can("reasons.manage");
  const list = useQuery({ queryKey: ["reasons", "page"], queryFn: () => get<Page<Reason>>("reasons/?limit=500") });

  const save = useMutation({
    mutationFn: (v: Partial<Reason>) => (editing?.id ? patch(`reasons/${editing.id}/`, v) : post("reasons/", v)),
    onSuccess: () => { message.success(t("common.saved")); setEditing(null); qc.invalidateQueries({ queryKey: ["reasons"] }); },
    onError: (e) => message.error(error(e)),
  });
  const toggle = useMutation({
    mutationFn: (r: Reason) => patch(`reasons/${r.id}/`, { is_active: !r.is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["reasons"] }),
    onError: (e) => message.error(error(e)),
  });

  const open = (r: Partial<Reason> | null) => {
    setEditing(r ?? {});
    form.setFieldsValue(r ?? { applies_to: "both", category: "other", requires_note: false, is_active: true, sort_order: 100, default_for: null });
  };

  return (
    <>
      <div className="oc-page-header">
        <h2>{t("menu.reasons")}</h2>
        {editable && <Button type="primary" icon={<PlusOutlined />} onClick={() => open(null)}>{t("reasons.new")}</Button>}
      </div>
      <Table<Reason>
        rowKey="id" size="middle" loading={list.isLoading} dataSource={list.data?.results ?? []} pagination={false} scroll={{ x: 900 }}
        onRow={(r) => ({ onDoubleClick: () => editable && open(r) })}
        columns={[
          { title: t("reasons.sortOrder"), dataIndex: "sort_order", width: 70, render: (v) => num(v) },
          { title: t("reasons.code"), dataIndex: "code", render: (v) => <Ltr>{v}</Ltr> },
          { title: t("reasons.nameFa"), dataIndex: "name_fa" },
          { title: t("reasons.nameEn"), dataIndex: "name_en", render: (v) => <span dir="ltr">{v}</span> },
          { title: t("reasons.appliesTo"), dataIndex: "applies_to", render: (v) => t(`reasons.applies.${v}`) },
          { title: t("reasons.category"), dataIndex: "category", render: (v) => t(`reasons.categories.${v}`) },
          { title: t("reasons.requiresNote"), dataIndex: "requires_note", render: (v) => (v ? t("common.yes") : t("common.no")) },
          { title: t("reasons.defaultFor"), dataIndex: "default_for", render: (v) => (v ? <Tag color="purple">{t(`reasons.defaults.${v}`)}</Tag> : "") },
          { title: t("common.status"), dataIndex: "is_active", render: (v, r) => <Switch checked={v} disabled={!editable} loading={toggle.isPending && toggle.variables?.id === r.id} onChange={() => toggle.mutate(r)} /> },
          ...(editable ? [{ title: "", render: (_: unknown, r: Reason) => <Button size="small" onClick={() => open(r)}>{t("common.edit")}</Button> }] : []),
        ]}
      />
      <Modal open={editing !== null} title={editing?.id ? t("common.edit") : t("reasons.new")} onCancel={() => setEditing(null)}
        onOk={() => form.submit()} okText={t("common.save")} cancelText={t("common.cancel")} confirmLoading={save.isPending} destroyOnHidden>
        <Form form={form} layout="vertical" onFinish={(v) => save.mutate(v)}>
          <Form.Item name="code" label={t("reasons.code")} rules={[{ required: true, pattern: /^[a-z0-9_-]+$/ }]}>
            <Input dir="ltr" disabled={!!editing?.id} />
          </Form.Item>
          <Form.Item name="name_fa" label={t("reasons.nameFa")} rules={[{ required: true }]}><Input dir="rtl" /></Form.Item>
          <Form.Item name="name_en" label={t("reasons.nameEn")} rules={[{ required: true }]}><Input dir="ltr" /></Form.Item>
          <Form.Item name="applies_to" label={t("reasons.appliesTo")}>
            <Select options={(["short", "extra", "both"] as const).map((v) => ({ value: v, label: t(`reasons.applies.${v}`) }))} />
          </Form.Item>
          <Form.Item name="category" label={t("reasons.category")}>
            <Select options={(["stock", "picking", "scanning", "other"] as const).map((v) => ({ value: v, label: t(`reasons.categories.${v}`) }))} />
          </Form.Item>
          <Form.Item name="default_for" label={t("reasons.defaultFor")}>
            <Select allowClear options={(["extra", "not_in_order"] as const).map((v) => ({ value: v, label: t(`reasons.defaults.${v}`) }))} />
          </Form.Item>
          <Form.Item name="sort_order" label={t("reasons.sortOrder")}><InputNumber min={0} /></Form.Item>
          <Form.Item name="requires_note" label={t("reasons.requiresNote")} valuePropName="checked"><Switch /></Form.Item>
          <Form.Item name="is_active" label={t("common.active")} valuePropName="checked"><Switch /></Form.Item>
        </Form>
      </Modal>
    </>
  );
}
