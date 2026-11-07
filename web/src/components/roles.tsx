import { useQuery } from "@tanstack/react-query";
import { Tag } from "antd";
import { get } from "../api/client";
import type { AppRole } from "../api/types";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";

const COLORS: Record<string, string> = { admin: "red", supervisor: "blue", checker: "green", stocktaker: "orange" };

/** All roles (built-in and custom). Needs users.manage or permissions.manage. */
export function useRoles() {
  const { can } = useAuth();
  return useQuery({
    queryKey: ["roles"], queryFn: () => get<AppRole[]>("roles/"), staleTime: 30_000,
    enabled: can("users.manage") || can("permissions.manage"),
  });
}

export function roleName(r: { code: string; name_fa: string; name_en: string } | undefined, code: string, lang: string) {
  if (!r) return code;
  return (lang === "en" ? r.name_en : r.name_fa) || r.name_fa || r.name_en || code;
}

export function RoleTags({ codes }: { codes: string[] }) {
  const { lang } = useI18n();
  const roles = useRoles();
  const byCode = Object.fromEntries((roles.data ?? []).map((r) => [r.code, r]));
  return <>{codes.map((c) => <Tag key={c} color={COLORS[c] ?? "purple"}>{roleName(byCode[c], c, lang)}</Tag>)}</>;
}
