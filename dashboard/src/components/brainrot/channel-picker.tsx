"use client";

import { useId, useMemo, useState, useTransition } from "react";
import { saveChannels } from "@/app/(dashboard)/g/[guildId]/brainrot/actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/field";
import type { Channel, WatchedChannel } from "@/lib/bot/schemas";
import { FeedbackNotice, useFeedback } from "./feedback";

const TYPE_LABEL: Record<string, string> = { text: "text", announcement: "announcements", voice: "voice", stage: "stage", forum: "forum", media: "media", thread: "thread" };
const WATCHABLE = new Set(["text", "announcement", "voice", "forum", "media", "thread"]);

/** A searchable checkbox list grouped by category; save sends the whole list and the bot diffs it. */
export function ChannelPicker({ guildId, channels, watched, limit }: { guildId: string; channels: Channel[]; watched: WatchedChannel[]; limit: number }) {
  const [selected, setSelected] = useState<Set<string>>(() => new Set(watched.map((channel) => channel.id)));
  const [query, setQuery] = useState("");
  const [pending, start] = useTransition();
  const [feedback, report] = useFeedback();
  const searchId = useId();

  const saved = useMemo(() => new Set(watched.map((channel) => channel.id)), [watched]);
  const [seen, setSeen] = useState(saved);
  if (seen !== saved) {
    // fresh data from the server (after a save, or someone else's change): adopt it
    setSeen(saved);
    setSelected(new Set(saved));
  }
  const dirty = selected.size !== saved.size || [...selected].some((id) => !saved.has(id));

  const groups = useMemo(() => {
    const wanted = query.trim().toLowerCase();
    const byCategory = new Map<string, { name: string; items: Channel[] }>();
    for (const channel of channels) {
      if (!channel.type || !WATCHABLE.has(channel.type)) continue;
      if (wanted && !channel.name.toLowerCase().includes(wanted) && !(channel.category?.name.toLowerCase().includes(wanted) ?? false)) continue;
      const key = channel.category?.id ?? "";
      const group = byCategory.get(key) ?? { name: channel.category?.name ?? "No category", items: [] };
      group.items.push(channel);
      byCategory.set(key, group);
    }
    return [...byCategory.values()];
  }, [channels, query]);

  // watched ids that are no longer channels here (deleted, or threads the list can't show)
  const orphans = watched.filter((channel) => !channels.some((candidate) => candidate.id === channel.id));

  function toggle(id: string, on: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  function save() {
    start(async () => {
      const result = await saveChannels(guildId, [...selected]);
      report(result);
      if (result.ok && result.data) setSelected(new Set(result.data.channels.map((channel) => channel.id)));
      // on a refusal the page revalidates with what the bot applied; the checkboxes follow on the next render
    });
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div className="flex flex-1 flex-col gap-1.5 sm:max-w-sm">
          <label htmlFor={searchId} className="text-sm font-medium">
            Find a channel
          </label>
          <Input id={searchId} type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="general, off-topic…" autoComplete="off" />
        </div>
        <p className="text-sm text-fg-muted">
          <span className="mono text-fg">{selected.size}</span> / {limit} selected
        </p>
      </div>

      <div className="card flex max-h-[28rem] flex-col overflow-y-auto p-0">
        {groups.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-fg-muted">No channels match.</p>
        ) : (
          groups.map((group) => (
            <fieldset key={group.name} className="border-b border-border last:border-b-0">
              <legend className="sr-only">{group.name}</legend>
              <p aria-hidden="true" className="eyebrow sticky top-0 bg-surface px-4 py-2">
                {group.name}
              </p>
              <ul>
                {group.items.map((channel) => {
                  const on = selected.has(channel.id);
                  const full = !on && selected.size >= limit;
                  return (
                    <li key={channel.id}>
                      <label className={`flex cursor-pointer items-center gap-3 px-4 py-2 text-sm hover:bg-surface-2 ${full ? "opacity-50" : ""}`}>
                        <input type="checkbox" checked={on} disabled={full || pending} onChange={(event) => toggle(channel.id, event.target.checked)} className="size-4 accent-[var(--accent)]" />
                        <span className="min-w-0 flex-1 truncate">
                          <span className="text-fg-faint">#</span>
                          {channel.name}
                        </span>
                        <span className="text-xs text-fg-faint">{TYPE_LABEL[channel.type ?? ""] ?? channel.type}</span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            </fieldset>
          ))
        )}
      </div>

      {orphans.length > 0 ? (
        <div className="flex flex-col gap-2 text-sm">
          <p className="text-fg-muted">Also watched, but not a channel the picker can show (a thread, or something deleted):</p>
          <ul className="flex flex-wrap gap-1.5">
            {orphans.map((channel) => (
              <li key={channel.id} className="inline-flex items-center gap-1.5">
                <Badge tone={channel.exists ? "neutral" : "danger"}>
                  {channel.name ? `#${channel.name}` : <span className="mono">{channel.id}</span>}
                  {!channel.exists ? " · gone" : ""}
                </Badge>
                {selected.has(channel.id) ? (
                  <button type="button" onClick={() => toggle(channel.id, false)} className="text-xs text-fg-muted underline-offset-2 hover:text-fg hover:underline">
                    stop watching
                  </button>
                ) : (
                  <button type="button" onClick={() => toggle(channel.id, true)} className="text-xs text-fg-muted underline-offset-2 hover:text-fg hover:underline">
                    undo
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <p className="text-sm text-fg-faint">Threads and forum posts inside a watched channel are watched too.</p>

      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" onClick={save} pending={pending} disabled={!dirty}>
          Save channels
        </Button>
        {dirty ? (
          <Button variant="ghost" onClick={() => setSelected(new Set(saved))} disabled={pending}>
            Discard changes
          </Button>
        ) : null}
      </div>
      <FeedbackNotice feedback={feedback} />
    </div>
  );
}
