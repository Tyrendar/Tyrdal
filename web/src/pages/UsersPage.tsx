import { PlusOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Form, Input, Modal, Select, Space, Switch, Table } from "antd";
import { useState } from "react";
import { get, patch, post } from "../api/client";
import { useAuth } from "../auth";
import { Ltr } from "../components/common";
import { RoleTags, roleName, useRoles } from "../components/roles";
import { useI18n } from "../i18n";

interface ActivityRow { id: number; username: string; full_name: string; roles: string[]; is_active: boolean; last_login: string | null; scans_today: number }

export default function UsersPage() {
  const { t, num, dateTime, error, lang } = useI18n();
  const { user: me } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const roles = useRoles();
  const [editing, setEditing] = useState<Partial<ActivityRow> | null>(null);
  const [pwFor, setPwFor] = useState<ActivityRow | null>(null);
  const [roleFilter, setRoleFilter] = useState<string | undefined>();
  const [form] = Form.useForm();
  const [pwForm] = Form.useForm<{ password: string }>();
  const list = useQuery({ queryKey: ["users", roleFilter], queryFn: () => get<ActivityRow[]>(`users/activity/${roleFilter ? `?role=${roleFilter}` : ""}`) });
  const invalidate = () => { qc.invalidateQueries({ queryKey: ["users"] }); qc.invalidateQueries({ queryKey: ["checkers"] }); qc.invalidateQueries({ queryKey: ["stocktakers"] }); qc.invalidateQueries({ queryKey: ["roles"] }); };

  const save = useMutation({
    mutationFn: (v: Record<string, unknown>) => (editing?.id ? patch(`users/${editing.id}/`, v) : post("users/", v)),
    onSuccess: () => { message.success(t("common.saved")); setEditing(null); invalidate(); },
    onError: (e) => message.error(error(e)),
  });
  const setActive = useMutation({
    mutationFn: (u: ActivityRow) => patch(`users/${u.id}/`, { is_active: !u.is_active }),
    onSuccess: invalidate,
    onError: (e) => message.error(error(e)),
  });
  const resetPw = useMutation({
    mutationFn: (v: { password: string }) => post(`users/${pwFor!.id}/reset-password/`, v),
    onSuccess: () => { message.success(t("common.saved")); setPwFor(null); pwForm.resetFields(); },
    onError: (e) => message.error(error(e)),
  });

  const isAdmin = me?.roles?.includes("admin");
  // Only admins can grant the admin role.
  const roleOptions = (roles.data ?? []).filter((r) => isAdmin || r.code !== "admin").map((r) => ({ value: r.code, label: roleName(r, r.code, lang) }));

  return (
    <>
      <div className="oc-page-header">
        <h2>{t("menu.users")}</h2>
        <Space>
          <Select allowClear placeholder={t("users.role")} style={{ width: 180 }} value={roleFilter} onChange={setRoleFilter}
            options={(roles.data ?? []).map((r) => ({ value: r.code, label: roleName(r, r.code, lang) }))} />
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing({}); form.setFieldsValue({ roles: ["checker"], username: "", full_name: "", password: "" }); }}>{t("users.new")}</Button>
        </Space>
      </div>
      <Table<ActivityRow>
        rowKey="id" size="middle" loading={list.isLoading} dataSource={list.data ?? []} scroll={{ x: 800 }} pagination={{ pageSize: 50, hideOnSinglePage: true }}
        columns={[
          { title: t("users.username"), dataIndex: "username", render: (v) => <Ltr>{v}</Ltr> },
          { title: t("users.fullName"), dataIndex: "full_name" },
          { title: t("users.roles"), dataIndex: "roles", render: (codes: string[]) => <RoleTags codes={codes} /> },
          { title: t("users.lastLogin"), dataIndex: "last_login", render: (v) => dateTime(v) },
          { title: t("users.scansToday"), dataIndex: "scans_today", render: (v) => num(v) },
          { title: t("common.status"), dataIndex: "is_active", render: (v, u) => <Switch checked={v} disabled={u.id === me?.id} onChange={() => setActive.mutate(u)} /> },
          {
            title: "", render: (_, u) => (
              <Space>
                <Button size="small" onClick={() => { setEditing(u); form.setFieldsValue(u); }}>{t("common.edit")}</Button>
                <Button size="small" onClick={() => setPwFor(u)}>{t("users.resetPassword")}</Button>
              </Space>
            ),
          },
        ]}
      />

      <Modal open={editing !== null} title={editing?.id ? t("common.edit") : t("users.new")} onCancel={() => setEditing(null)}
        onOk={() => form.submit()} okText={t("common.save")} cancelText={t("common.cancel")} confirmLoading={save.isPending} destroyOnHidden>
        <Form form={form} layout="vertical" onFinish={(v) => save.mutate(v)}>
          <Form.Item name="username" label={t("users.username")} rules={[{ required: true, pattern: /^[\w.@+-]+$/ }]}>
            <Input dir="ltr" disabled={!!editing?.id} autoComplete="off" />
          </Form.Item>
          <Form.Item name="full_name" label={t("users.fullName")} rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="roles" label={t("users.roles")} extra={t("users.rolesHint")} rules={[{ required: true, type: "array", min: 1 }]}>
            <Select mode="multiple" options={roleOptions} />
          </Form.Item>
          {!editing?.id && (
            <Form.Item name="password" label={t("users.password")} rules={[{ required: true, min: 4 }]}><Input.Password dir="ltr" autoComplete="new-password" /></Form.Item>
          )}
        </Form>
      </Modal>

      <Modal open={pwFor !== null} title={`${t("users.resetPassword")} · ${pwFor?.username ?? ""}`} onCancel={() => setPwFor(null)}
        onOk={() => pwForm.submit()} okText={t("common.save")} cancelText={t("common.cancel")} confirmLoading={resetPw.isPending} destroyOnHidden>
        <Form form={pwForm} layout="vertical" onFinish={(v) => resetPw.mutate(v)}>
          <Form.Item name="password" label={t("users.newPassword")} rules={[{ required: true, min: 4 }]}><Input.Password dir="ltr" autoComplete="new-password" /></Form.Item>
        </Form>
      </Modal>
    </>
  );
}
