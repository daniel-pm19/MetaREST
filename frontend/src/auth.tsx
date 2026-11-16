import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { permissionsFor, type Permissions, type User } from "./api/admin";
import { api, session } from "./api/client";

interface Auth {
  user: User | null;
  /** loading = comprobando una sesión guardada; out = hay que iniciar sesión */
  status: "loading" | "in" | "out";
  can: Permissions;
  notice: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const Ctx = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<Auth["status"]>(session.token ? "loading" : "out");
  const [notice, setNotice] = useState<string | null>(null);

  const logout = useCallback(() => {
    session.set(null);
    setUser(null);
    setStatus("out");
  }, []);

  useEffect(() => {
    session.onUnauthorized(() => {
      setNotice("Tu sesión expiró. Inicia sesión de nuevo.");
      logout();
    });
    if (!session.token) return;
    api.me().then(
      (u) => {
        setUser(u);
        setStatus("in");
      },
      () => logout(),
    );
  }, [logout]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await api.login(email, password);
    session.set(res.access_token);
    setNotice(null);
    setUser(res.user);
    setStatus("in");
  }, []);

  const value = useMemo<Auth>(() => ({ user, status, can: permissionsFor(user?.role), notice, login, logout }), [user, status, notice, login, logout]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth fuera de AuthProvider");
  return v;
}
