import * as RT from "@radix-ui/react-toast";
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { X } from "lucide-react";
import clsx from "clsx";
import { ApiError } from "@/lib/api";

type Variant = "info" | "success" | "error" | "warning";
interface ToastItem {
  id: number;
  title: string;
  description?: string;
  variant: Variant;
}

interface ToastApi {
  toast: (t: { title: string; description?: string; variant?: Variant }) => void;
  error: (e: unknown, fallback?: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);
let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const toast = useCallback<ToastApi["toast"]>(({ title, description, variant = "info" }) => {
    const id = nextId++;
    setItems((xs) => [...xs.slice(-4), { id, title, description, variant }]);
  }, []);
  const error = useCallback<ToastApi["error"]>(
    (e, fallback = "Something went wrong") => {
      const msg = e instanceof ApiError ? e.message : fallback;
      toast({ title: fallback === "Something went wrong" ? "Error" : fallback, description: msg, variant: "error" });
    },
    [toast],
  );
  return (
    <ToastContext.Provider value={{ toast, error }}>
      <RT.Provider swipeDirection="right" duration={5000}>
        {children}
        {items.map((t) => (
          <RT.Root
            key={t.id}
            className={clsx("toast", `toast-${t.variant}`)}
            onOpenChange={(open) => !open && setItems((xs) => xs.filter((x) => x.id !== t.id))}
            type={t.variant === "error" ? "foreground" : "background"}
          >
            <div className="toast-text">
              <RT.Title className="toast-title">{t.title}</RT.Title>
              {t.description && <RT.Description className="toast-description">{t.description}</RT.Description>}
            </div>
            <RT.Close className="btn btn-ghost btn-sm btn-icon" aria-label="Dismiss">
              <X size={16} />
            </RT.Close>
          </RT.Root>
        ))}
        <RT.Viewport className="toast-viewport" />
      </RT.Provider>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast outside ToastProvider");
  return ctx;
}
