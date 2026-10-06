"use client";

import { useState, type ReactNode } from "react";
import { Button, type ButtonProps } from "@/components/ui/button";

/** Two clicks for anything punitive or destructive: the button turns into an inline "sure?" row. */
export function ConfirmButton({
  prompt,
  confirmLabel = "Yes, do it",
  onConfirm,
  children,
  pending,
  ...rest
}: Omit<ButtonProps, "onClick"> & { prompt: ReactNode; confirmLabel?: string; onConfirm: () => void }) {
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return (
      <Button {...rest} pending={pending} onClick={() => setAsking(true)}>
        {children}
      </Button>
    );
  }
  return (
    <span role="group" aria-label="Confirm" className="inline-flex flex-wrap items-center gap-2 text-sm">
      <span className="text-fg-muted">{prompt}</span>
      <Button
        size="sm"
        variant={rest.variant === "danger" ? "danger" : "primary"}
        pending={pending}
        onClick={() => {
          setAsking(false);
          onConfirm();
        }}
      >
        {confirmLabel}
      </Button>
      <Button size="sm" variant="ghost" onClick={() => setAsking(false)} disabled={pending}>
        Cancel
      </Button>
    </span>
  );
}
