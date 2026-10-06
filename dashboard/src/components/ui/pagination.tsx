import Link from "next/link";
import type { PageMeta } from "@/lib/bot/schemas";

export function Pagination({ page, href }: { page: PageMeta; href: (page: number) => string }) {
  if (page.pages <= 1) return null;
  const link = "inline-flex h-9 items-center rounded-[var(--radius-control)] border border-border bg-surface-2 px-3 text-sm hover:border-border-strong";
  const disabled = "pointer-events-none opacity-40";
  return (
    <nav aria-label="Pagination" className="flex items-center justify-between gap-3 text-sm text-fg-muted">
      <Link href={href(page.page - 1)} aria-disabled={page.page <= 1} className={`${link} ${page.page <= 1 ? disabled : ""}`}>
        Previous
      </Link>
      <span className="mono">
        {page.page} / {page.pages}
      </span>
      <Link href={href(page.page + 1)} aria-disabled={page.page >= page.pages} className={`${link} ${page.page >= page.pages ? disabled : ""}`}>
        Next
      </Link>
    </nav>
  );
}
