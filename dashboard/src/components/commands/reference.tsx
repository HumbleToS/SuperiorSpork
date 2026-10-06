"use client";

import { useDeferredValue, useId, useMemo, useState } from "react";
import type { CommandCategory, CommandsIndex } from "@/lib/bot/schemas";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty";
import { CopyButton } from "./copy-button";

/**
 * The command reference, shared by the public page and every server's dashboard. One component, one
 * source: the bot's own help index. Search filters instantly; categories collapse on their own.
 */
/** `/brainrot pardon` → the group in blue, the subcommand in aqua; a lone name is all blue. */
function CommandName({ name }: { name: string }) {
  const space = name.indexOf(" ");
  if (space === -1) return <span className="text-blue">{name}</span>;
  return (
    <>
      <span className="text-blue">{name.slice(0, space)}</span> <span className="text-aqua">{name.slice(space + 1)}</span>
    </>
  );
}

/** Usage strings from the bot: `<required>` in orange, `[optional]` in purple, the rest as written. */
function Usage({ text }: { text: string }) {
  return text.split(/(<[^>]+>|\[[^\]]+\])/g).map((part, index) =>
    part.startsWith("<") ? (
      <span key={index} className="text-orange">
        {part}
      </span>
    ) : part.startsWith("[") ? (
      <span key={index} className="text-purple">
        {part}
      </span>
    ) : (
      part
    ),
  );
}

export function CommandsReference({ index, compact = false }: { index: CommandsIndex; compact?: boolean }) {
  const [query, setQuery] = useState("");
  const deferred = useDeferredValue(query);
  const searchId = useId();

  const filtered = useMemo(() => filterIndex(index.categories, deferred), [index.categories, deferred]);
  const total = index.categories.reduce((sum, category) => sum + category.commands.length, 0);
  const shown = filtered.reduce((sum, category) => sum + category.commands.length, 0);
  const searching = deferred.trim().length > 0;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <label htmlFor={searchId} className="text-sm font-medium">
          Search commands
        </label>
        <input
          id={searchId}
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="pardon, prefix, whois…"
          autoComplete="off"
          className="h-11 w-full rounded-[var(--radius-control)] border border-border bg-surface-2 px-3.5 text-base text-fg placeholder:text-fg-faint hover:border-border-strong focus:border-accent sm:max-w-md"
        />
        <p className="text-sm text-fg-faint" aria-live="polite">
          {searching ? `${shown} of ${total} commands match` : `${total} commands in ${index.categories.length} categories`}
        </p>
      </div>

      {filtered.length === 0 ? (
        <EmptyState title="Nothing matches that">Try a shorter word, or clear the search to see everything.</EmptyState>
      ) : (
        <div className="flex flex-col gap-4">
          {filtered.map((category) => (
            <details key={category.name} open className="card group overflow-hidden p-0">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3.5 sm:px-5 [&::-webkit-details-marker]:hidden">
                <span className="min-w-0">
                  <h2 className="text-base font-semibold text-yellow">
                    {category.emoji ? <span aria-hidden="true">{category.emoji} </span> : null}
                    {category.name}
                  </h2>
                  <span className="block truncate text-sm text-fg-muted">{category.blurb}</span>
                </span>
                <span className="flex shrink-0 items-center gap-2 text-sm text-fg-faint">
                  <span className="mono text-purple">{category.commands.length}</span>
                  <svg aria-hidden="true" viewBox="0 0 20 20" className="size-4 transition-transform group-open:rotate-180" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M5 8l5 5 5-5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </span>
              </summary>
              <ul className="divide-y divide-border border-t border-border">
                {category.commands.map((command) => (
                  <li key={command.name} className={`flex flex-col gap-2 ${compact ? "px-4 py-3" : "px-4 py-4 sm:px-5"}`}>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                      <h3 className="mono text-[15px] font-medium">
                        <CommandName name={command.shown_name} />
                      </h3>
                      {command.permissions.map((permission) => (
                        <Badge key={permission} tone="warn" title="Needed to run this command">
                          {permission}
                        </Badge>
                      ))}
                      {command.guild_only ? <Badge tone="info">Servers only</Badge> : null}
                      {command.cooldown ? <Badge tone="neutral">{command.cooldown}</Badge> : null}
                      {!command.slash ? <Badge tone="purple">Prefix command</Badge> : null}
                    </div>
                    <p className="text-sm text-fg-muted">{command.details || command.description}</p>
                    <div className="flex flex-col gap-1.5 text-sm">
                      <div className="flex items-start gap-2">
                        <span className="mono w-14 shrink-0 pt-1 text-xs text-fg-faint">usage</span>
                        <code className="min-w-0 flex-1 rounded-md bg-surface-2 px-2 py-1 text-[13px] break-words text-fg">
                          <Usage text={command.usage} />
                        </code>
                        <CopyButton text={command.usage} />
                      </div>
                      {command.example && command.example !== command.usage ? (
                        <div className="flex items-start gap-2">
                          <span className="mono w-14 shrink-0 pt-1 text-xs text-fg-faint">example</span>
                          <code className="min-w-0 flex-1 rounded-md bg-surface-2 px-2 py-1 text-[13px] break-words text-fg-muted">{command.example}</code>
                        </div>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ul>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}

export function filterIndex(categories: CommandCategory[], query: string): CommandCategory[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return categories;
  const matches = (category: CommandCategory, haystack: string) => words.every((word) => haystack.includes(word) || category.name.toLowerCase().includes(word));
  return categories
    .map((category) => ({
      ...category,
      commands: category.commands.filter((command) =>
        matches(category, `${command.name} ${command.shown_name} ${command.description} ${command.details} ${command.usage}`.toLowerCase()),
      ),
    }))
    .filter((category) => category.commands.length > 0);
}
