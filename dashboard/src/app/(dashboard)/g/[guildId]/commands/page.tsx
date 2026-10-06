import { CommandsReference } from "@/components/commands/reference";
import { CommandsUnavailable } from "@/components/commands/unavailable";
import { Notice } from "@/components/ui/notice";
import { getCommandsCached } from "@/lib/bot/commands-cache";
import { TONES } from "@/modules/registry";

export const metadata = { title: "Commands" };

export default async function GuildCommandsPage() {
  const cached = await getCommandsCached();
  return (
    <div className="flex flex-col gap-5">
      <div>
        <p className={`eyebrow ${TONES.blue.text}`}>Commands</p>
        <h1 className="mt-1 text-2xl">Reference</h1>
        <p className="mt-1 text-sm text-fg-muted">The same reference as the public page, from the bot&rsquo;s own help.</p>
      </div>
      {cached?.stale ? <Notice tone="warn">The bot isn&rsquo;t answering right now, so this is the last copy it gave us.</Notice> : null}
      {cached ? <CommandsReference index={cached.index} compact /> : <CommandsUnavailable />}
    </div>
  );
}
