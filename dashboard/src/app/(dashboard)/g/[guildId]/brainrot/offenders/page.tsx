import { OffendersView } from "@/components/brainrot/offenders";
import { PageHeader } from "@/components/brainrot/page-header";
import { VisiblePoll } from "@/components/brainrot/poll";
import { BotOffline } from "@/components/shell/bot-offline";
import { requireSession } from "@/lib/auth/require";
import { getOffenders } from "@/lib/bot/client";
import { load } from "@/lib/bot/load";

export const metadata = { title: "Offenders" };

export default async function OffendersPage({ params, searchParams }: PageProps<"/g/[guildId]/brainrot/offenders">) {
  const { guildId } = await params;
  const query = await searchParams;
  const sort = query.sort === "lifetime" ? "lifetime" : "heat";
  const page = Math.max(1, Number.parseInt(typeof query.page === "string" ? query.page : "1", 10) || 1);
  const session = await requireSession(`/g/${guildId}/brainrot/offenders`);
  const loaded = await load(() => getOffenders(guildId, session.userId, page, sort));
  if (!loaded.ok) return <BotOffline detail={loaded.offline} />;
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Offenders" description="Everyone with heat or history. Refreshes every 30 seconds while you're looking." />
      <VisiblePoll />
      <OffendersView guildId={guildId} items={loaded.data.items} page={loaded.data.page} sort={sort} />
    </div>
  );
}
