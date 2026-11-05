import { Progress, Tag, Tooltip, Typography } from "antd";
import type { ReactNode } from "react";
import type { Discrepancy, LineState, OrderStatus, Problem } from "../api/types";
import { useI18n } from "../i18n";

/** Barcodes, IDs and codes: always left-to-right, Latin digits, never reordered by RTL. */
export function Ltr({ children, copy }: { children: ReactNode; copy?: boolean }) {
  const content = <bdi dir="ltr" className="ltr">{children}</bdi>;
  return copy && typeof children === "string"
    ? <Typography.Text copyable={{ text: children }} style={{ fontFamily: "inherit" }}>{content}</Typography.Text>
    : content;
}

const STATUS_COLORS: Record<OrderStatus, string> = {
  pending_assignment: "default", assigned: "blue", in_progress: "processing", completed: "success", cancelled: "error",
};

export function StatusTag({ status }: { status: OrderStatus }) {
  const { t } = useI18n();
  return <Tag color={STATUS_COLORS[status]}>{t(`status.${status}`)}</Tag>;
}

const LINE_COLORS: Record<LineState, string> = { pending: "default", partial: "gold", ok: "green", short: "red", extra: "magenta" };

export function LineStateTag({ state }: { state: LineState }) {
  const { t } = useI18n();
  return <Tag color={LINE_COLORS[state]}>{t(`lineState.${state}`)}</Tag>;
}

export function DiscrepancyTags({ items }: { items: Discrepancy[] }) {
  const { t, num, lang } = useI18n();
  const live = items.filter((d) => d.status !== "resolved");
  if (!live.length) return null;
  return (
    <>
      {live.map((d) => (
        <Tooltip key={d.id} title={`${t(`discStatus.${d.status}`)}${d.note ? ` — ${d.note}` : ""}`}>
          <Tag color={d.status === "open" ? "red" : d.type === "short" ? "volcano" : "purple"}>
            {t(`discType.${d.type}`)} {num(d.qty_boxes)} {t("common.boxes")}
            {d.reason_code ? ` · ${reasonLabel(d.reason_code, lang)}` : ""}
          </Tag>
        </Tooltip>
      ))}
    </>
  );
}

// Filled by ReasonsCache in App so tags can show the reason name without another request.
export const reasonNames: Record<string, { fa: string; en: string }> = {};
function reasonLabel(code: string, lang: "fa" | "en") {
  return reasonNames[code]?.[lang] ?? code;
}

export function OrderProgress({ done, total, issues }: { done: number; total: number; issues?: number }) {
  const { num } = useI18n();
  const pct = total ? Math.round((100 * done) / total) : 0;
  return (
    <div style={{ minWidth: 120 }}>
      <Progress percent={pct} size="small" status={issues ? "exception" : pct === 100 ? "success" : "active"}
        format={() => `${num(done)}/${num(total)}`} />
    </div>
  );
}

/** Translated list of import/API problems such as {code: "units_mismatch", ...}. */
export function ProblemList({ items, type }: { items: Problem[]; type: "error" | "warning" }) {
  const { t } = useI18n();
  if (!items?.length) return null;
  return (
    <ul style={{ margin: 0, paddingInlineStart: 18 }}>
      {items.map((p, i) => {
        const { code, ...rest } = p;
        // Show the values that help fix the row; the column name and reason code are already implied by the message.
        const extras = Object.entries(rest)
          .filter(([k, v]) => v !== null && v !== undefined && v !== "" && k !== "reason")
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : String(v)}`);
        return (
          <li key={i}>
            <Typography.Text type={type === "error" ? "danger" : "warning"}>{t(`codes.${code}`, code)}</Typography.Text>
            {extras.length > 0 && <Typography.Text type="secondary"> (<Ltr>{extras.join(" · ")}</Ltr>)</Typography.Text>}
          </li>
        );
      })}
    </ul>
  );
}
