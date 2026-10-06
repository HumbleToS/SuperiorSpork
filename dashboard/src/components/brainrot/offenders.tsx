import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty";
import { Pagination } from "@/components/ui/pagination";
import type { Offender, PageMeta } from "@/lib/bot/schemas";
import { formatNumber, relativeTime } from "@/lib/format";
import { HeatBar } from "./heat-bar";
import { PardonButton } from "./pardon-button";
import { TONES } from "@/modules/registry";

function Person({ offender }: { offender: Offender }) {
  return (
    <span className="flex min-w-0 items-center gap-2">
      {offender.avatar ? (
        // eslint-disable-next-line @next/next/no-img-element -- Discord CDN avatar
        <img src={offender.avatar} alt="" className="size-7 shrink-0 rounded-full" />
      ) : (
        <span aria-hidden="true" className="size-7 shrink-0 rounded-full bg-surface-3" />
      )}
      <span className="min-w-0">
        <span className="block truncate font-medium text-fg">{offender.name ?? <span className="mono">{offender.user_id}</span>}</span>
        {!offender.in_guild ? <span className="block text-xs text-fg-faint">not in the server</span> : null}
      </span>
    </span>
  );
}

function Status({ offender }: { offender: Offender }) {
  return (
    <span className="flex flex-wrap gap-1">
      {offender.muted_until ? (
        <Badge tone="danger" title={offender.muted_until}>
          muted · ends {relativeTime(offender.muted_until)}
        </Badge>
      ) : null}
      {offender.repeat ? (
        <Badge tone="warn" title={offender.repeat_until ?? undefined}>
          repeat · strike {offender.escalation_level}
        </Badge>
      ) : null}
      {!offender.muted_until && !offender.repeat ? <Badge tone="neutral">clean</Badge> : null}
    </span>
  );
}

export function OffendersView({ guildId, items, page, sort }: { guildId: string; items: Offender[]; page: PageMeta; sort: "heat" | "lifetime" }) {
  const base = `/g/${guildId}/brainrot/offenders`;
  const href = (n: number) => `${base}?sort=${sort}&page=${n}`;
  const leaderboard = sort === "lifetime";

  return (
    <div className="flex flex-col gap-4">
      <nav aria-label="View" className="flex gap-1 border-b border-border">
        {(["heat", "lifetime"] as const).map((option) => (
          <Link
            key={option}
            href={`${base}?sort=${option}`}
            aria-current={sort === option ? "page" : undefined}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${sort === option ? `${TONES.orange.border} text-fg` : "border-transparent text-fg-muted hover:text-fg"}`}
          >
            {option === "heat" ? "Offenders" : "Leaderboard"}
          </Link>
        ))}
      </nav>

      {items.length === 0 ? (
        <EmptyState title={leaderboard ? "Nobody has been cooked here yet" : "Nobody is hot right now"}>
          {leaderboard ? "Lifetime offenses show up here once someone trips the word list." : "Heat cools a point an hour; anyone with history is on the leaderboard tab."}
        </EmptyState>
      ) : (
        <>
          <table className="hidden w-full border-separate border-spacing-0 text-sm md:table">
            <thead>
              <tr className="mono text-left text-xs text-fg-faint">
                {leaderboard ? <th className="pb-2 pl-3 font-medium">#</th> : null}
                <th className="pb-2 pl-3 font-medium">Member</th>
                <th className="pb-2 font-medium">{leaderboard ? "Title" : "Heat"}</th>
                <th className="pb-2 font-medium">Status</th>
                <th className="pb-2 font-medium">Lifetime</th>
                <th className="pb-2 pr-3 text-right font-medium">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((offender) => (
                <tr key={offender.user_id} className="card [&>td]:border-t [&>td]:border-border [&>td]:py-2.5 [&>td:first-child]:rounded-l-lg [&>td:last-child]:rounded-r-lg">
                  {leaderboard ? <td className="mono pl-3 text-purple">{offender.rank ?? "—"}</td> : null}
                  <td className="pl-3">
                    <Person offender={offender} />
                  </td>
                  <td>
                    {leaderboard ? (
                      <span className="flex flex-col">
                        <span>{offender.title}</span>
                        <HeatBar heat={offender.heat} max={offender.max_heat} className="mt-0.5" />
                      </span>
                    ) : (
                      <span className="flex flex-col">
                        <HeatBar heat={offender.heat} max={offender.max_heat} />
                        {offender.cooling_at ? <span className="text-xs text-fg-faint">next point cools {relativeTime(offender.cooling_at)}</span> : null}
                      </span>
                    )}
                  </td>
                  <td>
                    <Status offender={offender} />
                  </td>
                  <td>
                    <span className="mono">{formatNumber(offender.lifetime_offenses)}</span>
                    {leaderboard ? null : <span className="ml-1 text-xs text-fg-faint">{offender.title}</span>}
                  </td>
                  <td className="pr-3 text-right">{offender.in_guild ? <PardonButton guildId={guildId} userId={offender.user_id} name={offender.name ?? "them"} heat={offender.heat} /> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <ul className="flex flex-col gap-2 md:hidden">
            {items.map((offender) => (
              <li key={offender.user_id} className="card flex flex-col gap-3 p-3">
                <div className="flex items-start justify-between gap-3">
                  <Person offender={offender} />
                  {leaderboard && offender.rank ? <span className="mono text-sm text-purple">#{offender.rank}</span> : null}
                </div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <HeatBar heat={offender.heat} max={offender.max_heat} />
                  <span className="text-xs text-fg-muted">
                    {offender.title} · <span className="mono">{formatNumber(offender.lifetime_offenses)}</span> lifetime
                  </span>
                </div>
                <Status offender={offender} />
                {offender.in_guild ? <PardonButton guildId={guildId} userId={offender.user_id} name={offender.name ?? "them"} heat={offender.heat} /> : null}
              </li>
            ))}
          </ul>
        </>
      )}
      <Pagination page={page} href={href} />
    </div>
  );
}
