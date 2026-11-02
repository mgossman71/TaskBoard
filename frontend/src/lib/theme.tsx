import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type ThemeChoice = "light" | "dark" | "system";

const ThemeContext = createContext<{ theme: ThemeChoice; resolved: "light" | "dark"; setTheme: (t: ThemeChoice) => void } | null>(
  null,
);

function systemPrefersDark() {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeChoice>(() => {
    try {
      const t = localStorage.getItem("tb-theme");
      return t === "light" || t === "dark" ? t : "system";
    } catch {
      return "system";
    }
  });
  const [systemDark, setSystemDark] = useState(systemPrefersDark());

  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    const fn = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq?.addEventListener?.("change", fn);
    return () => mq?.removeEventListener?.("change", fn);
  }, []);

  const resolved = theme === "system" ? (systemDark ? "dark" : "light") : theme;

  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
  }, [resolved]);

  const setTheme = (t: ThemeChoice) => {
    setThemeState(t);
    try {
      if (t === "system") localStorage.removeItem("tb-theme");
      else localStorage.setItem("tb-theme", t);
    } catch {
      /* storage unavailable */
    }
  };

  return <ThemeContext.Provider value={{ theme, resolved, setTheme }}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme outside ThemeProvider");
  return ctx;
}
