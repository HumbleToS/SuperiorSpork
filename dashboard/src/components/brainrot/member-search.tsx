"use client";

import { useEffect, useId, useRef, useState, useTransition } from "react";
import { findMembers } from "@/app/(dashboard)/g/[guildId]/brainrot/actions";
import { Input } from "@/components/ui/field";
import { Spinner } from "@/components/ui/spinner";
import type { MemberRef } from "@/lib/bot/schemas";

/** Paste an id or a mention, or type a name: the bot resolves it from its own member cache. */
export function MemberSearch({ guildId, onPick, exclude = [], label = "Add a member", placeholder = "name, id, or @mention" }: { guildId: string; onPick: (member: MemberRef) => void; exclude?: string[]; label?: string; placeholder?: string }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<MemberRef[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const id = useId();
  const listId = useId();
  const latest = useRef(0);

  useEffect(() => {
    const wanted = query.trim();
    if (wanted.length < 2) return;
    const run = ++latest.current;
    const timer = setTimeout(() => {
      start(async () => {
        const result = await findMembers(guildId, wanted);
        if (run !== latest.current) return;
        if (result.ok) {
          setResults((result.data ?? []).filter((member) => !exclude.includes(member.id)));
          setProblem(null);
        } else {
          setResults([]);
          setProblem(result.error);
        }
      });
    }, 300);
    return () => clearTimeout(timer);
    // exclude changes on every pick; the list re-filters on the next keystroke, which is what we want
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [guildId, query]);

  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <div className="relative">
        <Input
          id={id}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            if (event.target.value.trim().length < 2) {
              latest.current++;
              setResults([]);
              setProblem(null);
            }
          }}
          placeholder={placeholder} autoComplete="off" role="combobox" aria-expanded={results.length > 0} aria-controls={listId} aria-autocomplete="list" />
        {pending ? <Spinner className="absolute top-3 right-3 size-4 text-fg-muted" /> : null}
      </div>
      {problem ? (
        <p className="text-sm text-danger" role="alert">
          {problem}
        </p>
      ) : null}
      {results.length > 0 ? (
        <ul id={listId} role="listbox" aria-label="Matches" className="card divide-y divide-border p-0">
          {results.map((member) => (
            <li key={member.id} role="option" aria-selected={false}>
              <button
                type="button"
                onClick={() => {
                  onPick(member);
                  setQuery("");
                  setResults([]);
                }}
                className="flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-surface-2"
              >
                {member.avatar ? (
                  // eslint-disable-next-line @next/next/no-img-element -- Discord CDN avatar
                  <img src={member.avatar} alt="" className="size-6 rounded-full" />
                ) : (
                  <span className="size-6 rounded-full bg-surface-3" aria-hidden="true" />
                )}
                <span className="min-w-0 flex-1 truncate">
                  {member.name ?? member.username}
                  {member.username && member.username !== member.name ? <span className="text-fg-faint"> · {member.username}</span> : null}
                </span>
                <span className="mono text-xs text-fg-faint">{member.id}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
