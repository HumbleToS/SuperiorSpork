"use client";

import { useId, useState, type KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/field";

/** A list of words with an add box: Enter or comma adds, × removes. Validation is the bot's; this only trims. */
export function ChipInput({
  label,
  help,
  values,
  onChange,
  placeholder,
  disabled,
  limit,
  minLength,
  maxLength,
}: {
  label: string;
  help?: string;
  values: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
  limit?: number;
  minLength?: number;
  maxLength?: number;
}) {
  const [draft, setDraft] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const id = useId();

  function add() {
    const pieces = draft
      .split(/[,\n]/)
      .map((piece) => piece.trim().toLowerCase())
      .filter(Boolean);
    if (pieces.length === 0) return;
    const next = [...values];
    for (const piece of pieces) {
      if (minLength !== undefined && piece.length < minLength) return setProblem(`"${piece}" is too short (${minLength}+ characters).`);
      if (maxLength !== undefined && piece.length > maxLength) return setProblem(`"${piece}" is too long (${maxLength} max).`);
      if (next.includes(piece)) continue;
      if (limit !== undefined && next.length >= limit) return setProblem(`That's the limit — ${limit} per server.`);
      next.push(piece);
    }
    setProblem(null);
    setDraft("");
    onChange(next);
  }

  function onKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      add();
    }
    if (event.key === "Backspace" && draft === "" && values.length > 0) onChange(values.slice(0, -1));
  }

  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {values.length > 0 ? (
        <ul className="flex flex-wrap gap-1.5" aria-label={`${label} list`}>
          {values.map((value) => (
            <li key={value} className="inline-flex items-center gap-1 rounded-[var(--radius-control)] border border-border bg-surface-2 py-0.5 pr-1 pl-2 text-sm">
              <span className="mono">{value}</span>
              <button
                type="button"
                aria-label={`Remove ${value}`}
                disabled={disabled}
                onClick={() => onChange(values.filter((candidate) => candidate !== value))}
                className="flex size-5 items-center justify-center rounded-[3px] text-fg-muted hover:bg-surface-3 hover:text-fg"
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="flex gap-2">
        <Input id={id} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={onKey} onBlur={add} placeholder={placeholder} disabled={disabled} autoComplete="off" />
        <Button onClick={add} disabled={disabled || !draft.trim()}>
          Add
        </Button>
      </div>
      {problem ? (
        <p className="text-sm text-danger" role="alert">
          {problem}
        </p>
      ) : help ? (
        <p className="text-sm text-fg-faint">{help}</p>
      ) : null}
    </div>
  );
}
