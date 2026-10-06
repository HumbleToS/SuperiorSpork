"use client";

export function Toggle({ checked, onChange, label, disabled, id }: { checked: boolean; onChange: (next: boolean) => void; label: string; disabled?: boolean; id?: string }) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-60 ${
        checked ? "border-green bg-green" : "border-border-strong bg-surface-3"
      }`}
    >
      <span
        aria-hidden="true"
        className={`inline-block size-5 rounded-full transition-transform duration-150 ${checked ? "translate-x-[22px] bg-canvas" : "translate-x-0.5 bg-fg-faint"}`}
      />
    </button>
  );
}
