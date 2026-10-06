"use client";

import { useEffect, useState } from "react";

export function CopyButton({ text, label = "Copy usage" }: { text: string; label?: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");

  useEffect(() => {
    if (state === "idle") return;
    const timer = setTimeout(() => setState("idle"), 1500);
    return () => clearTimeout(timer);
  }, [state]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
  }

  return (
    <button
      type="button"
      onClick={copy}
      aria-label={label}
      className="inline-flex h-7 shrink-0 items-center gap-1 rounded-md border border-border bg-surface-2 px-2 text-xs text-fg-muted hover:border-border-strong hover:text-fg"
    >
      <span aria-live="polite">{state === "copied" ? "Copied" : state === "failed" ? "Select and copy" : "Copy"}</span>
    </button>
  );
}
