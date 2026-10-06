"use client";

import { usePathname, useRouter } from "next/navigation";
import { useId, useTransition } from "react";
import type { GuildSummary } from "@/lib/bot/schemas";

/** A native select, on purpose: keyboard-native, screen-reader-native, and fine with a thumb. */
export function ServerSwitcher({ guilds, currentId }: { guilds: GuildSummary[]; currentId: string | null }) {
  const router = useRouter();
  const pathname = usePathname();
  const [pending, startTransition] = useTransition();
  const id = useId();
  const current = guilds.find((guild) => guild.id === currentId) ?? null;

  function go(guildId: string) {
    if (guildId === "__all__") {
      startTransition(() => router.push("/dashboard"));
      return;
    }
    // keep the module the admin is looking at when they switch servers
    const tail = currentId && pathname.startsWith(`/g/${currentId}/`) ? pathname.slice(`/g/${currentId}`.length) : "/commands";
    startTransition(() => router.push(`/g/${guildId}${tail}`));
  }

  return (
    <div className="flex min-w-0 items-center gap-2">
      <span aria-hidden="true" className="relative size-7 shrink-0 overflow-hidden rounded-[var(--radius-control)] border border-border bg-surface-3">
        {current?.icon ? (
          // eslint-disable-next-line @next/next/no-img-element -- Discord CDN icons, no optimization needed
          <img src={current.icon} alt="" className="size-full object-cover" />
        ) : (
          <span className="flex size-full items-center justify-center text-xs font-semibold text-fg-muted">{current?.name.slice(0, 1) ?? "·"}</span>
        )}
      </span>
      <label htmlFor={id} className="sr-only">
        Server
      </label>
      <select
        id={id}
        value={currentId ?? "__all__"}
        onChange={(event) => go(event.target.value)}
        disabled={pending}
        aria-busy={pending || undefined}
        className="select-arrow h-9 max-w-[46vw] min-w-0 appearance-none truncate rounded-[var(--radius-control)] border border-border bg-surface-2 py-0 pr-7 pl-2.5 text-sm font-medium text-fg hover:border-border-strong sm:max-w-xs"
      >
        <option value="__all__">All servers</option>
        {guilds.map((guild) => (
          <option key={guild.id} value={guild.id}>
            {guild.name}
          </option>
        ))}
      </select>
    </div>
  );
}
