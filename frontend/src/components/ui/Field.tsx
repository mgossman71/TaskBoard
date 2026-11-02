import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import clsx from "clsx";

interface FieldShellProps {
  label: string;
  error?: string;
  hint?: ReactNode;
  id: string;
  children: ReactNode;
  hideLabel?: boolean;
}

function FieldShell({ label, error, hint, id, children, hideLabel }: FieldShellProps) {
  return (
    <div className={clsx("field", error && "field-invalid")}>
      <label htmlFor={id} className={clsx("field-label", hideLabel && "sr-only")}>
        {label}
      </label>
      {children}
      {hint && !error && (
        <p id={`${id}-hint`} className="field-hint">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="field-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function describedBy(id: string, error?: string, hint?: ReactNode) {
  return error ? `${id}-error` : hint ? `${id}-hint` : undefined;
}

type InputProps = InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string; hint?: ReactNode; hideLabel?: boolean };

export const TextField = forwardRef<HTMLInputElement, InputProps>(function TextField(
  { label, error, hint, id, className, hideLabel, ...rest },
  ref,
) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <FieldShell label={label} error={error} hint={hint} id={fid} hideLabel={hideLabel}>
      <input
        ref={ref}
        id={fid}
        className={clsx("input", className)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fid, error, hint)}
        {...rest}
      />
    </FieldShell>
  );
});

type TextAreaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string; error?: string; hint?: ReactNode; hideLabel?: boolean };

export const TextAreaField = forwardRef<HTMLTextAreaElement, TextAreaProps>(function TextAreaField(
  { label, error, hint, id, className, hideLabel, ...rest },
  ref,
) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <FieldShell label={label} error={error} hint={hint} id={fid} hideLabel={hideLabel}>
      <textarea
        ref={ref}
        id={fid}
        className={clsx("input textarea", className)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fid, error, hint)}
        {...rest}
      />
    </FieldShell>
  );
});

type SelectProps = SelectHTMLAttributes<HTMLSelectElement> & { label: string; error?: string; hint?: ReactNode; hideLabel?: boolean };

export const SelectField = forwardRef<HTMLSelectElement, SelectProps>(function SelectField(
  { label, error, hint, id, className, children, hideLabel, ...rest },
  ref,
) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <FieldShell label={label} error={error} hint={hint} id={fid} hideLabel={hideLabel}>
      <select
        ref={ref}
        id={fid}
        className={clsx("input select", className)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(fid, error, hint)}
        {...rest}
      >
        {children}
      </select>
    </FieldShell>
  );
});
