"use client";

import { useEffect } from "react";

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <main id="main" className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-4 px-4 text-center">
      <h1 className="text-2xl font-semibold">Something went wrong</h1>
      <p className="text-fg-muted">Nothing was changed. Try again; if it keeps happening, the bot may be down.</p>
      <button type="button" onClick={reset} className="h-10 rounded-[var(--radius-control)] bg-primary px-4 font-medium text-primary-fg hover:bg-primary-hover">
        Try again
      </button>
    </main>
  );
}
