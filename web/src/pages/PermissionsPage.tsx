import { DeleteOutlined, EditOutlined, PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Checkbox, Form, Input, Modal, Popconfirm, Space, Table, Tooltip, Typography } from "antd";
import { useEffect, useState } from "react";
import { del, get, patch, post, put } from "../api/client";
import type { AppRole, PermissionMatrix } from "../api/types";
import { useAuth } from "../auth";
import { Ltr } from "../components/common";
import { roleName, useRoles } from "../components/roles";
import { useI18n } from "../i18n";

/** Grouping of permissions into the two sides of the app (plus shared). */
const GROUPS: { key: string; perms: string[] }[] = [
  { key: "checking", perms: ["orders.view", "orders.import", "orders.assign", "orders.manage", "barcodes.manage", "reasons.manage", "reports.view", "checking.perform"] },
  { key: "stocktaking", perms: ["stocktake.manage", "stocktake.perform"] },
  { key: "system", perms: ["users.manage", "permissions.manage", "audit.view"] },
];

export default function PermissionsPage() {
  const { t, d, error, lang, num } = useI18n();
  const { can } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const roles = useRoles();
  const m = useQuery({ queryKey: ["permissions"], queryFn: () => get<PermissionMatrix>("role-permissions/") });
  const [draft, setDraft] = useState<Record<string, Set<string>>>({});
  const [editing, setEditing] = useState<Partial<AppRole> | null>(null);
  const [form] = Form.useForm();
  const editable = can("permissions.manage");
  const columns = (roles.data ?? []);
  const editableRoles = columns.filter((r) => r.code !== "admin");

  useEffect(() => {
    if (m.data) setDraft(Object.fromEntries(Object.entries(m.data.roles).map(([r, ps]) => [r, new Set(ps)])));
  }, [m.data]);
  const dirty = editableRoles.filter((r) => {
    const a = new Set(m.data?.roles[r.code] ?? []), b = draft[r.code] ?? new Set();
    return a.size !== b.size || [...a].some((x) => !b.has(x));
  });

  const refresh = () => { qc.invalidateQueries({ queryKey: ["permissions"] }); qc.invalidateQueries({ queryKey: ["roles"] }); };
  const save = useMutation({
    mutationFn: async () => { for (const r of dirty) await put("role-permissions/", { role: r.code, permissions: [...(draft[r.code] ?? [])] }); },
    onSuccess: () => { message.success(t("common.saved")); refresh(); },
    onError: (e) => message.error(error(e)),
  });
  const saveRole = useMutation({
    mutationFn: (v: Partial<AppRole>) => (editing?.id ? patch(`roles/${editing.id}/`, v) : post("roles/", v)),
    onSuccess: () => { message.success(t("common.saved")); setEditing(null); refresh(); },
    onError: (e) => message.error(error(e)),
  });
  const removeRole = useMutation({
    mutationFn: (r: AppRole) => del(`roles/${r.id}/`),
    onSuccess: refresh,
    onError: (e) => message.error(error(e)),
  });
  const toggle = (role: string, perm: string, on: boolean) =>
    setDraft((x) => { const s = new Set(x[role]); if (on) s.add(perm); else s.delete(perm); return { ...x, [role]: s }; });

  const known = new Set(GROUPS.flatMap((g) => g.perms));
  const all = Object.keys(m.data?.permissions ?? {});
  const groups = [...GROUPS, { key: "other", perms: all.filter((p) => !known.has(p)) }].filter((g) => g.perms.some((p) => all.includes(p)));
  type RowT = { key: string; group?: string; perm?: string };
  const rows: RowT[] = groups.flatMap((g) => [{ key: `g:${g.key}`, group: g.key }, ...g.perms.filter((p) => all.includes(p)).map((p) => ({ key: p, perm: p }))]);

  const header = (r: AppRole) => (
    <Space direction="vertical" size={0} align="center">
      <span>{roleName(r, r.code, lang)}</span>
      <Typography.Text type="secondary" style={{ fontSize: 11 }}>{t("permissions.usersN").replace("{n}", num(r.users))}</Typography.Text>
      {editable && r.code !== "admin" && (
        <Space size={2}>
          <Tooltip title={t("common.edit")}><Button size="small" type="text" icon={<EditOutlined />} onClick={() => { setEditing(r); form.setFieldsValue(r); }} /></Tooltip>
          {!r.is_system && (
            <Popconfirm title={t("permissions.deleteRole")} onConfirm={() => removeRole.mutate(r)}>
              <Button size="small" type="text" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          )}
        </Space>
      )}
    </Space>
  );

  return (
    <>
      <div className="oc-page-header">
        <h2>{t("permissions.title")}</h2>
        {editable && (
          <Space>
            <Button icon={<PlusOutlined />} onClick={() => { setEditing({}); form.setFieldsValue({ name_fa: "", name_en: "" }); }}>{t("permissions.newRole")}</Button>
            <Button type="primary" disabled={!dirty.length} loading={save.isPending} onClick={() => save.mutate()}>{t("common.save")}</Button>
          </Space>
        )}
      </div>
      <Alert type="info" showIcon message={t("permissions.adminNote")} description={t("permissions.multiNote")} style={{ marginBottom: 12 }} />
      <Table<RowT>
        className="oc-perm-table" rowKey="key" size="small" loading={m.isLoading || roles.isLoading} dataSource={rows} pagination={false}
        tableLayout="auto" scroll={{ x: "max-content" }}
        rowClassName={(r) => (r.group ? "oc-perm-group" : "")}
        columns={[
          {
            title: t("common.details"), fixed: "left",
            render: (_, r) => (r.group ? <b>{t(`permissions.groups.${r.group}`)}</b>
              : <>{d.permissions.labels[r.perm!] ?? r.perm} <Ltr><small style={{ color: "#94a3b8" }}>{r.perm}</small></Ltr></>),
          },
          ...columns.map((role) => ({
            title: header(role), key: role.code, align: "center" as const,
            render: (_: unknown, r: RowT) => (r.group ? null : role.code === "admin" ? <Checkbox checked disabled />
              : <Checkbox disabled={!editable} checked={draft[role.code]?.has(r.perm!) ?? false} onChange={(e) => toggle(role.code, r.perm!, e.target.checked)} />),
          })),
        ]}
      />
      <Modal open={editing !== null} title={editing?.id ? t("common.edit") : t("permissions.newRole")} onCancel={() => setEditing(null)}
        onOk={() => form.submit()} okText={t("common.save")} cancelText={t("common.cancel")} confirmLoading={saveRole.isPending} destroyOnHidden>
        <Form form={form} layout="vertical" onFinish={(v) => saveRole.mutate(v)}>
          <Form.Item name="name_fa" label={t("permissions.nameFa")} rules={[{ required: true, whitespace: true }]}><Input /></Form.Item>
          <Form.Item name="name_en" label={t("permissions.nameEn")}><Input dir="ltr" /></Form.Item>
          {!editing?.id && <Typography.Text type="secondary">{t("permissions.newRoleHint")}</Typography.Text>}
        </Form>
      </Modal>
    </>
  );
}
