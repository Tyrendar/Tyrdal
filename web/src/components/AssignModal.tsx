import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Form, Input, Modal, Select } from "antd";
import { get, post } from "../api/client";
import type { Checker } from "../api/types";
import { useI18n } from "../i18n";

type Mode = "assign" | "reassign" | "bulk";

export function useCheckers(enabled = true) {
  return useQuery({ queryKey: ["checkers"], queryFn: () => get<Checker[]>("checkers/"), enabled, staleTime: 10_000 });
}

export default function AssignModal({ open, mode, orderIds, currentCheckerId, onClose }: {
  open: boolean; mode: Mode; orderIds: number[]; currentCheckerId?: number | null; onClose: () => void;
}) {
  const { t, num, error } = useI18n();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [form] = Form.useForm<{ checker_id: number; reason?: string }>();
  const checkers = useCheckers(open);

  const m = useMutation({
    mutationFn: async (v: { checker_id: number; reason?: string }) => {
      if (mode === "bulk") return post<{ assigned: number[]; failed: { order_id: number; code: string }[] }>("orders/bulk-assign/", { order_ids: orderIds, checker_id: v.checker_id });
      return post(`orders/${orderIds[0]}/${mode}/`, v);
    },
    onSuccess: (res) => {
      const failed = (res as { failed?: { code: string }[] })?.failed ?? [];
      if (failed.length) message.warning(`${t("codes." + failed[0].code, failed[0].code)} (${num(failed.length)})`);
      else message.success(t("common.saved"));
      qc.invalidateQueries({ queryKey: ["orders"] });
      qc.invalidateQueries({ queryKey: ["order"] });
      qc.invalidateQueries({ queryKey: ["summary"] });
      qc.invalidateQueries({ queryKey: ["checkers"] });
      form.resetFields();
      onClose();
    },
    onError: (e) => message.error(error(e)),
  });

  const title = mode === "reassign" ? t("order.reassign") : mode === "bulk" ? `${t("order.bulkAssign")} (${num(orderIds.length)} ${t("order.selected")})` : t("order.assign");

  return (
    <Modal open={open} title={title} onCancel={onClose} onOk={() => form.submit()} okText={t("common.confirm")}
      cancelText={t("common.cancel")} confirmLoading={m.isPending} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={(v) => m.mutate(v)}>
        <Form.Item name="checker_id" label={t("order.selectChecker")} rules={[{ required: true }]}>
          <Select
            showSearch
            size="large"
            loading={checkers.isLoading}
            optionFilterProp="label"
            options={(checkers.data ?? []).filter((c) => c.id !== currentCheckerId).map((c) => ({
              value: c.id,
              label: `${c.name} (${num(c.active_orders)} ${t("order.activeOrders")})`,
            }))}
          />
        </Form.Item>
        {mode === "reassign" && (
          <Form.Item name="reason" label={t("order.reasonOptional")}><Input maxLength={300} /></Form.Item>
        )}
      </Form>
    </Modal>
  );
}
