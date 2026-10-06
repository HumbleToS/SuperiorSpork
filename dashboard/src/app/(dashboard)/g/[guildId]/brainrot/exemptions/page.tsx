import { ExemptionsEditor } from "@/components/brainrot/exemptions-editor";
import { PageHeader } from "@/components/brainrot/page-header";
import { BotOffline } from "@/components/shell/bot-offline";
import { requireSession } from "@/lib/auth/require";
import { getBrainrotDefaults, getExemptions, getGuildMeta } from "@/lib/bot/client";
import { load } from "@/lib/bot/load";

export const metadata = { title: "Exemptions" };

export default async function ExemptionsPage({ params }: PageProps<"/g/[guildId]/brainrot/exemptions">) {
  const { guildId } = await params;
  const session = await requireSession(`/g/${guildId}/brainrot/exemptions`);
  const loaded = await load(() => Promise.all([getGuildMeta(guildId, session.userId), getExemptions(guildId, session.userId), getBrainrotDefaults()]));
  if (!loaded.ok) return <BotOffline detail={loaded.offline} />;
  const [meta, exemptions, defaults] = loaded.data;
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Exemptions" description="Roles and members the heat system leaves alone." />
      <ExemptionsEditor guildId={guildId} roles={meta.roles} exemptions={exemptions} limit={defaults.limits.exemptions} />
    </div>
  );
}
