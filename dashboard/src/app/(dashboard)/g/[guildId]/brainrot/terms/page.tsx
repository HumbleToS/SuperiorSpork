import { PageHeader } from "@/components/brainrot/page-header";
import { TermsEditor } from "@/components/brainrot/terms-editor";
import { BotOffline } from "@/components/shell/bot-offline";
import { requireSession } from "@/lib/auth/require";
import { getBrainrotDefaults, getTerms } from "@/lib/bot/client";
import { load } from "@/lib/bot/load";

export const metadata = { title: "Terms" };

export default async function TermsPage({ params }: PageProps<"/g/[guildId]/brainrot/terms">) {
  const { guildId } = await params;
  const session = await requireSession(`/g/${guildId}/brainrot/terms`);
  const loaded = await load(() => Promise.all([getTerms(guildId, session.userId), getBrainrotDefaults()]));
  if (!loaded.ok) return <BotOffline detail={loaded.offline} />;
  const [terms, defaults] = loaded.data;
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Terms" description="The vocabulary this server scores. Detection is a word list — no model ever decides what counts." />
      <TermsEditor guildId={guildId} terms={terms} defaults={defaults} />
    </div>
  );
}
