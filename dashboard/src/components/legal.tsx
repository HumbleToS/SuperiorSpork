import type { ReactNode } from "react";

export function LegalPage({ title, updated, children }: { title: string; updated: string; children: ReactNode }) {
  return (
    <article className="mx-auto flex max-w-3xl flex-col gap-6">
      <header className="flex flex-col gap-2 border-b border-border pb-6">
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">{title}</h1>
        <p className="text-sm text-fg-faint">
          Last updated <time dateTime={updated}>{updated}</time>
        </p>
      </header>
      <div className="legal flex flex-col gap-5 text-[15px] leading-7 text-fg-muted [&_h2]:mt-4 [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:text-fg [&_h3]:text-base [&_h3]:font-semibold [&_h3]:text-fg [&_li]:ml-5 [&_li]:list-disc [&_strong]:text-fg [&_code]:text-fg">
        {children}
      </div>
    </article>
  );
}
