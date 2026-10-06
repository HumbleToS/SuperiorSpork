import { Badge } from "@/components/ui/badge";
import type { Action } from "@/lib/bot/schemas";
import { describeConfigValue, describeDuration, FIELD_LABELS, formatDateTime, relativeTime } from "@/lib/format";

const TONES: Record<Action["action"], "neutral" | "ok" | "warn" | "danger" | "info"> = {
  warning: "warn",
  spam: "warn",
  mute: "danger",
  timeout: "danger",
  pardon: "ok",
  config: "info",
};

const LABELS: Record<Action["action"], string> = {
  warning: "Warning",
  spam: "Spam",
  mute: "Mute",
  timeout: "Timeout",
  pardon: "Pardon",
  config: "Setting",
};

function Person({ who, fallback }: { who: Action["target"]; fallback: string }) {
  if (!who) return <span className="text-fg-faint">{fallback}</span>;
  return (
    <span className="inline-flex items-center gap-1.5">
      {who.avatar ? (
        // eslint-disable-next-line @next/next/no-img-element -- Discord CDN avatar
        <img src={who.avatar} alt="" className="size-4 rounded-full" />
      ) : null}
      <span className="font-medium text-fg">{who.name ?? who.username ?? <span className="mono">{who.id}</span>}</span>
    </span>
  );
}

export function describeAction(action: Action): string {
  switch (action.action) {
    case "warning":
      return `heat ${action.heat ?? "?"}/5${action.heat_added ? ` (+${action.heat_added})` : ""}`;
    case "spam":
      return `spam window filled, heat ${action.heat ?? "?"}/5`;
    case "mute":
      return action.applied ? `muted for ${action.duration_seconds ? describeDuration(action.duration_seconds) : "a while"}` : "earned a mute the bot couldn't apply";
    case "timeout":
      return action.applied
        ? `repeat offense, strike ${action.escalation_level ?? "?"} — timed out for ${action.duration_seconds ? describeDuration(action.duration_seconds) : "a while"}`
        : `repeat offense, strike ${action.escalation_level ?? "?"} — timeout not applied`;
    case "pardon":
      return action.heat_added ? `${Math.abs(action.heat_added)} heat taken off, now ${action.heat ?? 0}/5` : "heat cleared, repeat list cleared";
    case "config": {
      const label = action.field ? (FIELD_LABELS[action.field] ?? action.field) : "setting";
      if (action.before === null) return `${label}: added ${describeConfigValue(action.field, action.after)}`;
      if (action.after === null) return `${label}: removed ${describeConfigValue(action.field, action.before)}`;
      return `${label}: ${describeConfigValue(action.field, action.before)} → ${describeConfigValue(action.field, action.after)}`;
    }
  }
}

export function ActionRow({ action }: { action: Action }) {
  return (
    <li className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-start sm:gap-4">
      <div className="flex shrink-0 items-center gap-2 sm:w-40">
        <Badge tone={TONES[action.action]}>{LABELS[action.action]}</Badge>
        <Badge tone="neutral">{action.source}</Badge>
      </div>
      <div className="min-w-0 flex-1 text-sm">
        <p className="text-fg-muted">
          {action.action === "config" ? (
            <>
              <Person who={action.actor} fallback="Someone" /> changed {describeAction(action)}
            </>
          ) : (
            <>
              <Person who={action.target} fallback="Someone" /> — {describeAction(action)}
              {action.actor ? (
                <>
                  {" "}
                  by <Person who={action.actor} fallback="an admin" />
                </>
              ) : null}
            </>
          )}
        </p>
      </div>
      <time dateTime={action.at} title={formatDateTime(action.at)} className="mono shrink-0 text-xs text-fg-faint sm:pt-0.5">
        {relativeTime(action.at)}
      </time>
    </li>
  );
}
