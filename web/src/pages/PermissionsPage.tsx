import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Checkbox, Table } from "antd";
import { useEffect, useState } from "react";
import { get, put } from "../api/client";
import type { PermissionMatrix, Role } from "../api/types";
import { useAuth } from "../auth";
import { Ltr } from "../components/common";
import { useI18n } from "../i18n";

const EDITABLE: Role[] = ["supervisor", "checker"];

export default function PermissionsPage() {
  const { t, d, error } = useI18n();
  const { can } = useAuth();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const m = useQuery({ queryKey: ["permissions"], queryFn: () => get<PermissionMatrix>("role-permissions/") });
  const [draft, setDraft] = useState<Record<string, Set<string>>>({});
  useEffect(() => {
    if (m.data) setDraft(Object.fromEntries(EDITABLE.map((r) => [r, new Set(m.data!.roles[r])])));
  }, [m.data]);

  const save = useMutation({
    mutationFn: async () => { for (const r of EDITABLE) await put("role-permissions/", { role: r, permissions: [...(draft[r] ?? [])] }); },
    onSuccess: () => { message.success(t("common.saved")); qc.invalidateQueries({ queryKey: ["permissions"] }); },
    onError: (e) => message.error(error(e)),
  });

  const editable = can("permissions.manage");
  const perms = Object.keys(m.data?.permissions ?? {});
  const toggle = (role: string, perm: string, on: boolean) =>
    setDraft((d) => { const s = new Set(d[role]); if (on) s.add(perm); else s.delete(perm); return { ...d, [role]: s }; });

  return (
    <>
      <div className="oc-page-header">
        <h2>{t("permissions.title")}</h2>
        {editable && <Button type="primary" loading={save.isPending} onClick={() => save.mutate()}>{t("common.save")}</Button>}
      </div>
      <Alert type="info" showIcon message={t("permissions.adminNote")} style={{ marginBottom: 12 }} />
      <Table
        rowKey={(p) => p} size="middle" loading={m.isLoading} dataSource={perms} pagination={false}
        columns={[
          { title: t("common.details"), render: (p: string) => <>{d.permissions.labels[p] ?? p} <Ltr><small style={{ color: "#94a3b8" }}>{p}</small></Ltr></> },
          { title: t("roles.admin"), align: "center", render: () => <Checkbox checked disabled /> },
          ...EDITABLE.map((r) => ({
            title: t(`roles.${r}`), align: "center" as const,
            render: (p: string) => <Checkbox disabled={!editable} checked={draft[r]?.has(p) ?? false} onChange={(e) => toggle(r, p, e.target.checked)} />,
          })),
        ]}
      />
    </>
  );
}
