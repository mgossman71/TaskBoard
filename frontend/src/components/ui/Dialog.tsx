import * as RD from "@radix-ui/react-dialog";
import * as AD from "@radix-ui/react-alert-dialog";
import { X } from "lucide-react";
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import clsx from "clsx";

export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  wide,
  className,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  wide?: boolean;
  className?: string;
}) {
  return (
    <RD.Root open={open} onOpenChange={onOpenChange}>
      <RD.Portal>
        <RD.Overlay className="overlay" />
        <RD.Content className={clsx("dialog", wide && "dialog-wide", className)} aria-describedby={description ? undefined : undefined}>
          <div className="dialog-header">
            <RD.Title className="dialog-title">{title}</RD.Title>
            <RD.Close className="btn btn-ghost btn-sm btn-icon" aria-label="Close">
              <X size={18} />
            </RD.Close>
          </div>
          {description ? (
            <RD.Description className="dialog-description">{description}</RD.Description>
          ) : (
            <RD.Description className="sr-only">{typeof title === "string" ? title : "Dialog"}</RD.Description>
          )}
          <div className="dialog-body">{children}</div>
        </RD.Content>
      </RD.Portal>
    </RD.Root>
  );
}

interface ConfirmOptions {
  title: string;
  description: ReactNode;
  confirmLabel?: string;
  destructive?: boolean;
}

const ConfirmContext = createContext<(o: ConfirmOptions) => Promise<boolean>>(async () => false);

/** Promise-based confirmation dialog for destructive operations. */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [opts, setOpts] = useState<ConfirmOptions | null>(null);
  const resolver = useRef<(v: boolean) => void>(() => undefined);
  const confirm = useCallback((o: ConfirmOptions) => {
    setOpts(o);
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve;
    });
  }, []);
  const close = (v: boolean) => {
    resolver.current(v);
    setOpts(null);
  };
  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <AD.Root open={!!opts} onOpenChange={(o) => !o && close(false)}>
        <AD.Portal>
          <AD.Overlay className="overlay" />
          <AD.Content className="dialog dialog-confirm">
            <AD.Title className="dialog-title">{opts?.title}</AD.Title>
            <AD.Description className="dialog-description">{opts?.description}</AD.Description>
            <div className="dialog-actions">
              <AD.Cancel className="btn btn-secondary btn-md">Cancel</AD.Cancel>
              <AD.Action
                className={clsx("btn btn-md", opts?.destructive ? "btn-danger" : "btn-primary")}
                onClick={() => close(true)}
              >
                {opts?.confirmLabel ?? "Confirm"}
              </AD.Action>
            </div>
          </AD.Content>
        </AD.Portal>
      </AD.Root>
    </ConfirmContext.Provider>
  );
}

export function useConfirm() {
  return useContext(ConfirmContext);
}
