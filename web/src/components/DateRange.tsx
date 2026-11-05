import * as rmdp from "react-multi-date-picker";
import gregorianM from "react-date-object/calendars/gregorian";
import persianM from "react-date-object/calendars/persian";
import gregorian_enM from "react-date-object/locales/gregorian_en";
import gregorian_faM from "react-date-object/locales/gregorian_fa";
import persian_enM from "react-date-object/locales/persian_en";
import persian_faM from "react-date-object/locales/persian_fa";
import type { ComponentType } from "react";
import { useI18n } from "../i18n";

// These packages are CommonJS; depending on the bundler's interop the default
// export can arrive wrapped in { default }. Unwrap once, explicitly.
const unwrap = <T,>(m: T): T => ((m as { default?: T })?.default ?? m);
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const DatePicker = unwrap(unwrap((rmdp as any).default)) as ComponentType<any>;
const DateObject = (rmdp as unknown as { DateObject: typeof rmdp.DateObject }).DateObject;
const gregorian = unwrap(gregorianM), persian = unwrap(persianM);
const gregorian_en = unwrap(gregorian_enM), gregorian_fa = unwrap(gregorian_faM);
const persian_en = unwrap(persian_enM), persian_fa = unwrap(persian_faM);

export type Preset = "today" | "week" | "month";

const iso = (d: InstanceType<typeof DateObject>) => new DateObject(d).convert(gregorian, gregorian_en).format("YYYY-MM-DD");

/**
 * Report periods as Gregorian ISO dates. Weeks start on Saturday (Iranian work week);
 * "month" is the Jalali month when the Jalali calendar is selected.
 */
export function presetRange(preset: Preset, calendar: "jalali" | "gregorian"): [string, string] {
  const cal = calendar === "jalali" ? persian : gregorian;
  const loc = calendar === "jalali" ? persian_en : gregorian_en;
  const today = new DateObject({ calendar: cal, locale: loc });
  if (preset === "today") return [iso(today), iso(today)];
  if (preset === "week") {
    const js = new Date();
    const back = (js.getDay() + 1) % 7; // days since Saturday
    const start = new DateObject({ calendar: cal, locale: loc }).subtract(back, "days");
    return [iso(start), iso(today)];
  }
  const first = new DateObject({ calendar: cal, locale: loc }).toFirstOfMonth();
  return [iso(first), iso(today)];
}

/** Date range picker that follows the selected calendar (Jalali by default) and
 *  always reports Gregorian ISO dates (YYYY-MM-DD) for the API. */
export function DateRange({ value, onChange }: { value: [string, string] | null; onChange: (v: [string, string] | null) => void }) {
  const { lang, calendar, t } = useI18n();
  const cal = calendar === "jalali" ? persian : gregorian;
  const loc = calendar === "jalali" ? (lang === "fa" ? persian_fa : persian_en) : (lang === "fa" ? gregorian_fa : gregorian_en);
  const current = value
    ? value.map((v) => new DateObject({ date: v, format: "YYYY-MM-DD", calendar: gregorian, locale: gregorian_en }).convert(cal, loc))
    : [];

  return (
    <DatePicker
      range
      value={current}
      calendar={cal}
      locale={loc}
      calendarPosition={lang === "fa" ? "bottom-right" : "bottom-left"}
      placeholder={t("common.dateRange")}
      inputClass="ant-input oc-date-input"
      onChange={(dates: unknown) => {
        const arr = (Array.isArray(dates) ? dates : []) as InstanceType<typeof DateObject>[];
        if (arr.length === 0) return onChange(null);
        if (arr.length < 2) return;
        const iso = arr.map((d) => new DateObject(d).convert(gregorian, gregorian_en).format("YYYY-MM-DD")) as [string, string];
        onChange(iso);
      }}
    />
  );
}
