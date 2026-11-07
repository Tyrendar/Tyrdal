import { CalculatorOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Card, Checkbox, Col, InputNumber, Modal, Progress, Row, Select, Space, Table, Tag, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";
import { post, put } from "../api/client";
import type { Checker } from "../api/types";
import { useI18n } from "../i18n";
import { useCheckers } from "./AssignModal";
import { Ltr } from "./common";

interface PlanOrder { id: number; reference_id: string; customer: string; boxes: number; lines: number; checker_id: number | null }
interface PlanChecker { id: number; name: string; capacity_boxes: number; load_today: number; target: number; assigned: number; orders: number }
interface Plan { total_boxes: number; level: number; checkers: PlanChecker[]; orders: PlanOrder[] }

const pctColor = (p: number) => (p > 105 ? "#dc2626" : p > 95 ? "#ca8a04" : "#0f766e");

/**
 * Capacity-based auto-assignment: set each checker's daily capacity (boxes), compute a plan for the
 * unassigned orders (or the selected ones), change any order's checker by hand, then apply.
 */
export default function AutoAssignModal({ open, orderIds, onClose }: { open: boolean; orderIds: number[]; onClose: () => void }) {
  const { t, num, error } = useI18n();
  const { message } = App.useApp();
  const qc = useQueryClient();
  const checkers = useCheckers(open);
  const [chosen, setChosen] = useState<number[] | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [mapping, setMapping] = useState<Record<number, number>>({});

  useEffect(() => { if (!open) { setPlan(null); setChosen(null); setMapping({}); } }, [open]);
  const list = checkers.data ?? [];
  const included = chosen ?? list.filter((c) => (c.capacity_boxes ?? 0) > 0).map((c) => c.id);

  const setCap = useMutation({
    mutationFn: ({ id, cap }: { id: number; cap: number | null }) => put(`checkers/${id}/capacity/`, { capacity_boxes: cap }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["checkers"] }),
    onError: (e) => message.error(error(e)),
  });
  const compute = useMutation({
    mutationFn: () => post<Plan>("orders/auto-assign/plan/", { order_ids: orderIds.length ? orderIds : undefined, checker_ids: included }),
    onSuccess: (p) => { setPlan(p); setMapping(Object.fromEntries(p.orders.filter((o) => o.checker_id).map((o) => [o.id, o.checker_id!]))); },
    onError: (e) => message.error(error(e)),
  });
  const apply = useMutation({
    mutationFn: () => post<{ assigned: number[]; failed: { order_id: number; reference_id?: string; code: string }[] }>(
      "orders/auto-assign/apply/", { assignments: Object.entries(mapping).map(([o, c]) => ({ order_id: Number(o), checker_id: c })) }),
    onSuccess: (r) => {
      if (r.failed.length) message.warning(t("auto.partly").replace("{a}", num(r.assigned.length)).replace("{f}", num(r.failed.length)));
      else message.success(t("auto.done").replace("{n}", num(r.assigned.length)));
      qc.invalidateQueries({ queryKey: ["orders"] });
      qc.invalidateQueries({ queryKey: ["checkers"] });
      qc.invalidateQueries({ queryKey: ["summary"] });
      onClose();
    },
    onError: (e) => message.error(error(e)),
  });

  // Live totals: follow manual changes in the table.
  const live = useMemo(() => {
    const boxes: Record<number, number> = {}, count: Record<number, number> = {};
    for (const o of plan?.orders ?? []) {
      const c = mapping[o.id];
      if (c) { boxes[c] = (boxes[c] ?? 0) + o.boxes; count[c] = (count[c] ?? 0) + 1; }
    }
    return { boxes, count };
  }, [plan, mapping]);
  const planCheckers = plan?.checkers ?? [];
  const nameOf = (id: number) => list.find((c) => c.id === id)?.name ?? planCheckers.find((c) => c.id === id)?.name ?? String(id);
  const checkerOptions = list.map((c) => ({ value: c.id, label: c.name }));

  return (
    <Modal open={open} onCancel={onClose} width={1000} title={<><ThunderboltOutlined /> {t("auto.title")}</>} destroyOnHidden
      footer={[
        <Button key="c" onClick={onClose}>{t("common.cancel")}</Button>,
        plan && <Button key="a" type="primary" disabled={!Object.keys(mapping).length} loading={apply.isPending} onClick={() => apply.mutate()}>
          {t("auto.apply").replace("{n}", num(Object.keys(mapping).length))}
        </Button>,
      ]}>
      <Typography.Paragraph type="secondary">{t("auto.hint")}</Typography.Paragraph>

      <Card size="small" title={t("auto.checkers")} style={{ marginBottom: 12 }}>
        <Table<Checker>
          rowKey="id" size="small" pagination={false} loading={checkers.isLoading} dataSource={list}
          columns={[
            {
              title: "", width: 40, render: (_, c) => (
                <Checkbox checked={included.includes(c.id)} disabled={!(c.capacity_boxes ?? 0)}
                  onChange={(e) => setChosen(e.target.checked ? [...included, c.id] : included.filter((x) => x !== c.id))} />
              ),
            },
            { title: t("order.checker"), dataIndex: "name" },
            {
              title: t("auto.capacity"), render: (_, c) => (
                <InputNumber min={0} max={1000000} step={100} style={{ width: 130 }} defaultValue={c.capacity_boxes ?? undefined}
                  placeholder={t("auto.noCapacity")} addonAfter={t("common.boxes")}
                  onBlur={(e) => {
                    const v = e.target.value.replace(/[^\d۰-۹]/g, "").replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)));
                    const cap = v === "" ? null : Number(v);
                    if (cap !== (c.capacity_boxes ?? null)) {
                      setCap.mutate({ id: c.id, cap });
                      if (cap && !included.includes(c.id)) setChosen([...included, c.id]);
                    }
                  }} />
              ),
            },
            { title: t("auto.loadToday"), dataIndex: "load_today", render: (v) => num(v) },
            {
              title: t("auto.free"), render: (_, c) => (c.capacity_boxes
                ? <Typography.Text type={c.load_today > c.capacity_boxes ? "danger" : undefined}>{num(Math.max(c.capacity_boxes - c.load_today, 0))}</Typography.Text>
                : t("common.none")),
            },
          ]}
        />
        <Space style={{ marginTop: 12 }}>
          <Button type="primary" icon={<CalculatorOutlined />} disabled={!included.length} loading={compute.isPending} onClick={() => compute.mutate()}>
            {plan ? t("auto.recompute") : t("auto.compute")}
          </Button>
          <Typography.Text type="secondary">
            {orderIds.length ? t("auto.scopeSelected").replace("{n}", num(orderIds.length)) : t("auto.scopeAll")}
          </Typography.Text>
        </Space>
      </Card>

      {plan && (
        <>
          {plan.orders.length === 0 && <Alert type="info" showIcon message={t("auto.nothing")} style={{ marginBottom: 12 }} />}
          {plan.level > 1.0001 && (
            <Alert type="warning" showIcon style={{ marginBottom: 12 }}
              message={t("auto.over").replace("{p}", num(Math.round(plan.level * 100)))} />
          )}
          <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
            {planCheckers.map((c) => {
              const assigned = live.boxes[c.id] ?? 0;
              const pct = Math.round((100 * (c.load_today + assigned)) / c.capacity_boxes);
              return (
                <Col key={c.id} flex="1 1 220px">
                  <Card size="small" title={c.name} extra={<Tag>{num(live.count[c.id] ?? 0)} {t("auto.ordersN")}</Tag>}>
                    <Progress percent={Math.min(pct, 100)} success={{ percent: Math.min(Math.round((100 * c.load_today) / c.capacity_boxes), 100) }}
                      strokeColor={pctColor(pct)} format={() => `${num(pct)}٪`} />
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {t("auto.cardLine").replace("{a}", num(assigned)).replace("{t}", num(c.target)).replace("{l}", num(c.load_today)).replace("{c}", num(c.capacity_boxes))}
                    </Typography.Text>
                  </Card>
                </Col>
              );
            })}
          </Row>
          <Table<PlanOrder>
            rowKey="id" size="small" dataSource={plan.orders} pagination={{ pageSize: 50, showSizeChanger: false, hideOnSinglePage: true }}
            columns={[
              { title: t("order.reference"), dataIndex: "reference_id", render: (v) => <Ltr>{v}</Ltr> },
              { title: t("order.customer"), dataIndex: "customer", render: (v) => <span className="oc-clip" title={v}>{v}</span> },
              { title: t("reports.lines"), dataIndex: "lines", render: num },
              { title: t("common.boxes"), dataIndex: "boxes", sorter: (a, b) => a.boxes - b.boxes, defaultSortOrder: "descend", render: (v) => <b>{num(v)}</b> },
              {
                title: t("order.checker"), render: (_, o) => (
                  <Select style={{ width: 200 }} value={mapping[o.id]} options={checkerOptions} allowClear placeholder={t("order.unassigned")}
                    onChange={(v) => setMapping((m) => { const n = { ...m }; if (v) n[o.id] = v; else delete n[o.id]; return n; })} />
                ),
                filters: planCheckers.map((c) => ({ text: nameOf(c.id), value: c.id })), onFilter: (v, o) => mapping[o.id] === v,
              },
            ]}
          />
        </>
      )}
    </Modal>
  );
}
