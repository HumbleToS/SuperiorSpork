import { Badge } from "@/components/ui/badge";
import { Notice } from "@/components/ui/notice";
import type { BotPermissions, Readiness } from "@/lib/bot/schemas";

const NEEDED: ReadonlyArray<[keyof BotPermissions, string, string]> = [
  ["moderate_members", "Moderate Members", "to time people out"],
  ["manage_roles", "Manage Roles", "only for role mode, to hand out the muted role"],
  ["manage_messages", "Manage Messages", "only if offending messages are deleted"],
  ["view_channel", "View Channel", "in every watched channel"],
  ["send_messages", "Send Messages", "to post warnings"],
  ["embed_links", "Embed Links", "to post cards"],
];

/** The permission health panel: the bot's own readiness lines, plus the exact fix for each missing permission. */
export function HealthPanel({ readiness, permissions, inviteUrl, guildId }: { readiness: Readiness; permissions: BotPermissions; inviteUrl: string | null; guildId: string }) {
  const reinvite = inviteUrl ? withGuild(inviteUrl, guildId) : null;
  const missing = NEEDED.filter(([key]) => !permissions[key]);
  return (
    <div className="flex flex-col gap-3">
      {readiness.ready ? (
        <Notice tone="success" title="Ready">
          The bot has everything it needs in this server.
        </Notice>
      ) : (
        <Notice tone="warn" title="Not ready yet — fix these first">
          <ul className="mt-1 flex flex-col gap-0.5">
            {readiness.problems.map((problem) => (
              <li key={problem}>· {problem}</li>
            ))}
          </ul>
        </Notice>
      )}
      <ul className="flex flex-wrap gap-1.5" aria-label="Bot permissions">
        {NEEDED.map(([key, label, why]) => (
          <li key={key}>
            <Badge tone={permissions[key] ? "ok" : "danger"} title={why}>
              <Mark ok={permissions[key]} />
              {label}
            </Badge>
          </li>
        ))}
      </ul>
      {missing.length > 0 && reinvite ? (
        <p className="text-sm text-fg-muted">
          Give the bot {missing.map(([, label]) => label).join(", ")} in Server Settings → Roles, or{" "}
          <a href={reinvite} className="text-accent underline-offset-4 hover:underline">
            re-invite it with the right permissions
          </a>
          .
        </p>
      ) : null}
    </div>
  );
}

function Mark({ ok }: { ok: boolean }) {
  return (
    <svg viewBox="0 0 12 12" aria-hidden="true" className="size-3" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {ok ? <path d="M2.5 6.5 5 9l4.5-6" /> : <path d="M3 3l6 6M9 3l-6 6" />}
    </svg>
  );
}

function withGuild(inviteUrl: string, guildId: string): string {
  const url = new URL(inviteUrl);
  url.searchParams.set("guild_id", guildId);
  url.searchParams.set("disable_guild_select", "true");
  return url.toString();
}
