import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError } from "../api/client";
import en from "./en";
import fa, { type Dict } from "./fa";

export type Lang = "fa" | "en";
export type Calendar = "jalali" | "gregorian";

const dicts: Record<Lang, Dict> = { fa, en };
const TZ = "Asia/Tehran";

function load<T extends string>(key: string, fallback: T, allowed: T[]): T {
  try {
    const v = localStorage.getItem(key) as T | null;
    return v && allowed.includes(v) ? v : fallback;
  } catch { return fallback; }
}
function store(key: string, v: string) { try { localStorage.setItem(key, v); } catch { /* ignore */ } }

interface I18n {
  lang: Lang; setLang: (l: Lang) => void; calendar: Calendar; setCalendar: (c: Calendar) => void;
  dir: "rtl" | "ltr"; d: Dict;
  /** Lookup by dotted path, e.g. t("status.completed"); returns the key if missing. */
  t: (path: string, fallback?: string) => string;
  num: (n: number | null | undefined) => string;
  /** "3 of 5": "۳ از ۵" in Persian, because "/" is the Persian decimal separator. */
  of: (n: number, total: number) => string;
  dateTime: (iso: string | null | undefined) => string;
  date: (iso: string | null | undefined) => string;
  duration: (seconds: number | null | undefined) => string;
  error: (e: unknown) => string;
}

const Ctx = createContext<I18n | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => load("oc.lang", "fa", ["fa", "en"]));
  const [calendar, setCalState] = useState<Calendar>(() => load("oc.calendar", "jalali", ["jalali", "gregorian"]));

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "fa" ? "rtl" : "ltr";
    document.title = dicts[lang].app.title;
  }, [lang]);

  const setLang = useCallback((l: Lang) => { setLangState(l); store("oc.lang", l); }, []);
  const setCalendar = useCallback((c: Calendar) => { setCalState(c); store("oc.calendar", c); }, []);

  const value = useMemo<I18n>(() => {
    const d = dicts[lang];
    const locale = `${lang === "fa" ? "fa-IR" : "en-GB"}-u-ca-${calendar === "jalali" ? "persian" : "gregory"}-nu-${lang === "fa" ? "arabext" : "latn"}`;
    const numFmt = new Intl.NumberFormat(lang === "fa" ? "fa-IR" : "en-US");
    const dtFmt = new Intl.DateTimeFormat(locale, { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
    const dFmt = new Intl.DateTimeFormat(locale, { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" });
    const t = (path: string, fallback?: string) => {
      let cur: unknown = d;
      for (const part of path.split(".")) {
        if (cur && typeof cur === "object" && part in (cur as Record<string, unknown>)) cur = (cur as Record<string, unknown>)[part];
        else return fallback ?? path;
      }
      return typeof cur === "string" ? cur : fallback ?? path;
    };
    const num = (n: number | null | undefined) => (n === null || n === undefined ? d.common.none : numFmt.format(n));
    return {
      lang, setLang, calendar, setCalendar, dir: lang === "fa" ? "rtl" : "ltr", d, t, num,
      of: (n, total) => (lang === "fa" ? `${num(n)} از ${num(total)}` : `${num(n)} / ${num(total)}`),
      dateTime: (iso) => (iso ? dtFmt.format(new Date(iso)) : d.common.none),
      date: (iso) => (iso ? dFmt.format(new Date(iso)) : d.common.none),
      duration: (s) => {
        if (s === null || s === undefined) return d.common.none;
        const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
        const pad = (x: number) => String(x).padStart(2, "0");
        const txt = `${h}:${pad(m)}:${pad(sec)}`;
        return lang === "fa" ? txt.replace(/\d/g, (c) => "۰۱۲۳۴۵۶۷۸۹"[Number(c)]) : txt;
      },
      error: (e) => {
        if (e instanceof ApiError) return d.codes[e.code] ?? e.message ?? e.code;
        return d.common.unknownError;
      },
    };
  }, [lang, calendar, setLang, setCalendar]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18n {
  const v = useContext(Ctx);
  if (!v) throw new Error("useI18n outside I18nProvider");
  return v;
}
