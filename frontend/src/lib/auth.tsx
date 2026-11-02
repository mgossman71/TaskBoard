import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, logoutRequest, refreshSession, setSessionExpiredHandler, setTokens } from "./api";
import type { TokenResponse, User } from "./types";

type Status = "loading" | "authenticated" | "anonymous";

interface AuthState {
  status: Status;
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName: string) => Promise<void>;
  logout: () => Promise<void>;
  setUser: (u: User) => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [user, setUser] = useState<User | null>(null);
  const qc = useQueryClient();

  const accept = useCallback((resp: TokenResponse) => {
    setTokens(resp);
    setUser(resp.user);
    setStatus("authenticated");
  }, []);

  const reset = useCallback(() => {
    setTokens(null);
    setUser(null);
    setStatus("anonymous");
    qc.clear();
  }, [qc]);

  useEffect(() => {
    let cancelled = false;
    refreshSession()
      .then((resp) => {
        if (cancelled) return;
        if (resp) accept(resp);
        else setStatus("anonymous");
      })
      .catch(() => !cancelled && setStatus("anonymous"));
    setSessionExpiredHandler(() => reset());
    return () => {
      cancelled = true;
      setSessionExpiredHandler(null);
    };
  }, [accept, reset]);

  const value = useMemo<AuthState>(
    () => ({
      status,
      user,
      setUser,
      login: async (email, password) => {
        const resp = await api.post<TokenResponse>("/auth/login", { email, password });
        qc.clear();
        accept(resp);
      },
      register: async (email, password, display_name) => {
        const resp = await api.post<TokenResponse>("/auth/register", { email, password, display_name });
        qc.clear();
        accept(resp);
      },
      logout: async () => {
        await logoutRequest();
        reset();
      },
    }),
    [status, user, accept, reset, qc],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
