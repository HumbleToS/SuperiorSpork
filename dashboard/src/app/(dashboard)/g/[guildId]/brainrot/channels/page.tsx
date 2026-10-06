import { ChannelPicker } from "@/components/brainrot/channel-picker";
import { PageHeader } from "@/components/brainrot/page-header";
import { BotOffline } from "@/components/shell/bot-offline";
import { requireSession } from "@/lib/auth/require";
import { getBrainrotDefaults, getChannels, getGuildMeta } from "@/lib/bot/client";
import { load } from "@/lib/bot/load";

export const metadata = { title: "Channels" };

export default async function ChannelsPage({ params }: PageProps<"/g/[guildId]/brainrot/channels">) {
  const { guildId } = await params;
  const session = await requireSession(`/g/${guildId}/brainrot/channels`);
  const loaded = await load(() => Promise.all([getGuildMeta(guildId, session.userId), getChannels(guildId, session.userId), getBrainrotDefaults()]));
  if (!loaded.ok) return <BotOffline detail={loaded.offline} />;
  const [meta, watched, defaults] = loaded.data;
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Channels" description="Only messages in these channels are scored. Nothing is watched until you pick something." />
      <ChannelPicker guildId={guildId} channels={meta.channels} watched={watched.channels} limit={defaults.limits.channels} />
    </div>
  );
}
