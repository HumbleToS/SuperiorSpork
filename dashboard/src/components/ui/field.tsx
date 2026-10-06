import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";

export function Field({ label, help, error, htmlFor, children }: { label: ReactNode; help?: ReactNode; error?: ReactNode; htmlFor?: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-sm font-medium text-fg">
        {label}
      </label>
      {children}
      {error ? (
        <p className="text-sm text-danger" role="alert">
          {error}
        </p>
      ) : help ? (
        <p className="text-sm text-fg-faint">{help}</p>
      ) : null}
    </div>
  );
}

const CONTROL =
  "h-10 w-full rounded-[var(--radius-control)] border border-border bg-surface-2 px-3 text-sm text-fg placeholder:text-fg-faint hover:border-border-strong focus:border-accent disabled:opacity-60";

export function Input({ className = "", ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...rest} className={`${CONTROL} ${className}`} />;
}

export function Select({ className = "", children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...rest} className={`${CONTROL} appearance-none pr-8 ${className}`}>
      {children}
    </select>
  );
}
