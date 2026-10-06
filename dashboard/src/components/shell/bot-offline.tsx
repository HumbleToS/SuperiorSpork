import { EmptyState } from "@/components/ui/empty";

export function BotOffline({ detail }: { detail?: string }) {
  return (
    <EmptyState title="The bot is unreachable">
      The dashboard talks to the bot for everything, and it isn&rsquo;t answering right now. Nothing was changed. Give it a minute and
      reload.{detail ? <span className="mt-2 block text-xs text-fg-faint">{detail}</span> : null}
    </EmptyState>
  );
}
