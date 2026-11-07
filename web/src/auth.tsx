import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, get, post, setUnauthorizedHandler, tokens } from "./api/client";
import type { User } from "./api/types";

interface Auth {
  user: User | null;
  ready: boolean;
  login: (username: string, password: string) => Promise<User>;
  logout: () => void;
  can: (perm: string) => boolean;
}

const Ctx = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  const logout = useCallback(() => { tokens.clear(); setUser(null); }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null));
    if (!tokens.access) { setReady(true); return; }
    get<User>("auth/me/").then(setUser).catch(() => tokens.clear()).finally(() => setReady(true));
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const d = await post<{ access: string; refresh: string; user: User }>("auth/login/", { username, password });
    if (d.user.role === "checker" || d.user.role === "stocktaker") throw new ApiError(403, "checker_not_allowed");
    tokens.set(d.access, d.refresh);
    setUser(d.user);
    return d.user;
  }, []);

  const value = useMemo<Auth>(() => ({
    user, ready, login, logout, can: (p) => !!user?.permissions.includes(p),
  }), [user, ready, login, logout]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): Auth {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
