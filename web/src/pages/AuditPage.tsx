import { useQuery } from "@tanstack/react-query";
import { Input, Table } from "antd";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { get, qs, type Page } from "../api/client";
import type { AuditEntry } from "../api/types";
import { DateRange } from "../components/DateRange";
import { Ltr } from "../components/common";
import { useI18n } from "../i18n";
import { JsonDiff } from "./OrderDetailPage";

export default function AuditPage() {
  const { t, num, dateTime } = useI18n();
  const nav = useNavigate();
  const [action, setAction] = useState("");
  const [range, setRange] = useState<[string, string] | null>(null);
  const [page, setPage] = useState(1);
  const query = qs({ action, from: range?.[0], to: range?.[1], limit: 50, offset: (page - 1) * 50 });
  const list = useQuery({ queryKey: ["audit", query], queryFn: () => get<Page<AuditEntry>>(`audit/${query}`) });

  return (
    <>
      <div className="oc-page-header"><h2>{t("menu.audit")}</h2></div>
      <div className="oc-toolbar">
        <Input.Search allowClear dir="ltr" placeholder="order. / user. / import." style={{ width: 220 }} onSearch={(v) => { setAction(v.trim()); setPage(1); }} />
        <DateRange value={range} onChange={(v) => { setRange(v); setPage(1); }} />
      </div>
      <Table<AuditEntry>
        rowKey="id" size="small" loading={list.isLoading} dataSource={list.data?.results ?? []} scroll={{ x: 1000 }}
        pagination={{ current: page, pageSize: 50, total: list.data?.count ?? 0, onChange: setPage, showSizeChanger: false, showTotal: (n) => `${t("common.total")}: ${num(n)}` }}
        columns={[
          { title: t("event.at"), dataIndex: "at", render: (v) => dateTime(v), width: 150 },
          { title: t("event.user"), dataIndex: "user" },
          { title: t("audit.action"), dataIndex: "action", render: (v) => <Ltr>{v}</Ltr> },
          { title: t("audit.entity"), render: (_, r) => <Ltr>{r.entity_type}:{r.entity_id}</Ltr> },
          { title: t("audit.order"), dataIndex: "order_reference", render: (v, r) => (v ? <a onClick={() => nav(`/orders/${r.order_id}`)}><Ltr>{v}</Ltr></a> : "") },
          { title: t("common.note"), dataIndex: "note" },
          { title: t("common.details"), render: (_, r) => <JsonDiff before={r.before} after={r.after} />, width: 360 },
        ]}
      />
    </>
  );
}
