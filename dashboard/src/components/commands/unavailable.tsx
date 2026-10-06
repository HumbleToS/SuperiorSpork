import { EmptyState } from "@/components/ui/empty";

export function CommandsUnavailable() {
  return (
    <EmptyState title="Commands are unavailable right now">
      The bot isn&rsquo;t answering, and there&rsquo;s no earlier copy to show yet. Try again in a minute.
    </EmptyState>
  );
}
