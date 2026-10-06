import { ActionRow } from "@/components/brainrot/action-row";
import { PageHeader } from "@/components/brainrot/page-header";
import { BotOffline } from "@/components/shell/bot-offline";
import { EmptyState } from "@/components/ui/empty";
import { Pagination } from "@/components/ui/pagination";
import { requireSession } from "@/lib/auth/require";
import { getActions } from "@/lib/bot/client";
import { load } from "@/lib/bot/load";
import { ActionKind, ActionSource } from "@/lib/bot/schemas";

export const metadata = { title: "Activity" };

const KIND_LABELS: Record<ActionKind, string> = { warning: "Warnings", spam: "Spam", mute: "Mutes", timeout: "Timeouts", pardon: "Pardons", config: "Settings" };
const SOURCE_LABELS: Record<ActionSource, string> = { auto: "Automatic", command: "Command", dashboard: "Dashboard" };

export default async function ActivityPage({ params, searchParams }: PageProps<"/g/[guildId]/brainrot/activity">) {
  const { guildId } = await params;
  const query = await searchParams;
  const action = ActionKind.safeParse(query.action);
  const source = ActionSource.safeParse(query.source);
  const filters = { action: action.success ? action.data : undefined, source: source.success ? source.data : undefined };
  const page = Math.max(1, Number.parseInt(typeof query.page === "string" ? query.page : "1", 10) || 1);
  const session = await requireSession(`/g/${guildId}/brainrot/activity`);
  const loaded = await load(() => getActions(guildId, session.userId, page, filters));
  if (!loaded.ok) return <BotOffline detail={loaded.offline} />;
  const base = `/g/${guildId}/brainrot/activity`;
  const href = (n: number) => {
    const url = new URLSearchParams();
    if (filters.action) url.set("action", filters.action);
    if (filters.source) url.set("source", filters.source);
    url.set("page", String(n));
    return `${base}?${url}`;
  };
  const control = "h-10 rounded-[var(--radius-control)] border border-border bg-surface-2 px-3 text-sm text-fg hover:border-border-strong";

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Activity" description="What the bot did and who changed what. Numbers and names only — never message text. Kept for 30 days." />
      <form method="get" action={base} className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          Type
          <select name="action" defaultValue={filters.action ?? ""} className={control}>
            <option value="">All</option>
            {ActionKind.options.map((kind) => (
              <option key={kind} value={kind}>
                {KIND_LABELS[kind]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          Source
          <select name="source" defaultValue={filters.source ?? ""} className={control}>
            <option value="">All</option>
            {ActionSource.options.map((kind) => (
              <option key={kind} value={kind}>
                {SOURCE_LABELS[kind]}
              </option>
            ))}
          </select>
        </label>
        <button type="submit" className="h-10 rounded-[var(--radius-control)] border border-border bg-surface-2 px-4 text-sm font-medium hover:border-border-strong">
          Filter
        </button>
      </form>
      {loaded.data.items.length === 0 ? (
        <EmptyState title="Nothing here">{filters.action || filters.source ? "Nothing matches those filters." : "Warnings, mutes, pardons, and settings changes show up here."}</EmptyState>
      ) : (
        <ul className="card divide-y divide-border p-0">
          {loaded.data.items.map((item) => (
            <ActionRow key={item.id} action={item} />
          ))}
        </ul>
      )}
      <Pagination page={loaded.data.page} href={href} />
    </div>
  );
}
