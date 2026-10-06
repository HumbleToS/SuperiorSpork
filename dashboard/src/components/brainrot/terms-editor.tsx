"use client";

import { useMemo, useState, useTransition } from "react";
import { saveAllowlist, saveTerms } from "@/app/(dashboard)/g/[guildId]/brainrot/actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import type { BrainrotDefaults, TermsLists } from "@/lib/bot/schemas";
import { ChipInput } from "./chip-input";
import { FeedbackNotice, useFeedback } from "./feedback";

const same = (a: string[], b: string[]) => a.length === b.length && a.every((value, index) => value === b[index]);

/** Defaults with a per-term switch (off = removed here), custom additions, and the allowlist. */
export function TermsEditor({ guildId, terms, defaults }: { guildId: string; terms: TermsLists; defaults: BrainrotDefaults }) {
  const [removed, setRemoved] = useState<string[]>(terms.removed);
  const [added, setAdded] = useState<string[]>(terms.added);
  const [allowed, setAllowed] = useState<string[]>(terms.allowed);
  const [pendingTerms, startTerms] = useTransition();
  const [pendingAllow, startAllow] = useTransition();
  const [termsFeedback, reportTerms] = useFeedback();
  const [allowFeedback, reportAllow] = useFeedback();
  const [seen, setSeen] = useState(terms);
  if (seen !== terms) {
    // fresh data from the server (after a save, or someone else's change): adopt it
    setSeen(terms);
    setRemoved(terms.removed);
    setAdded(terms.added);
    setAllowed(terms.allowed);
  }

  const termsDirty = !same(removed, terms.removed) || !same(added, terms.added);
  const allowDirty = !same(allowed, terms.allowed);
  const activeCount = useMemo(() => terms.defaults.filter((term) => !removed.includes(term) && !allowed.includes(term)).length + added.filter((term) => !allowed.includes(term)).length, [terms.defaults, removed, added, allowed]);

  function toggleDefault(term: string, on: boolean) {
    setRemoved((current) => (on ? current.filter((candidate) => candidate !== term) : [...current, term]));
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader title="Default list" description={`${terms.defaults.length} terms the bot ships with. Switch one off to ignore it in this server.`} />
        <ul className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
          {terms.defaults.map((term) => {
            const isAllowed = allowed.includes(term);
            const on = !removed.includes(term) && !isAllowed;
            return (
              <li key={term}>
                <label className={`flex cursor-pointer items-center gap-3 rounded-md px-2 py-1.5 text-sm hover:bg-surface-2 ${isAllowed ? "opacity-60" : ""}`}>
                  <input type="checkbox" checked={on} disabled={isAllowed || pendingTerms} onChange={(event) => toggleDefault(term, event.target.checked)} className="size-4 accent-[var(--accent)]" />
                  <span className="mono flex-1">{term}</span>
                  {isAllowed ? <Badge tone="info">allowed</Badge> : null}
                </label>
              </li>
            );
          })}
        </ul>
        <div className="mt-5 border-t border-border pt-5">
          <ChipInput
            label="Custom terms"
            help={`Words or short phrases this server also counts. Matching ignores case, accents, leetspeak, and stretched letters. Up to ${defaults.limits.custom_terms}.`}
            values={added}
            onChange={setAdded}
            placeholder="a word or phrase, Enter to add"
            disabled={pendingTerms}
            limit={defaults.limits.custom_terms}
            minLength={defaults.limits.term_length.min}
            maxLength={defaults.limits.term_length.max}
          />
        </div>
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <Button variant="primary" pending={pendingTerms} disabled={!termsDirty} onClick={() => startTerms(async () => reportTerms(await saveTerms(guildId, { added, removed })))}>
            Save vocabulary
          </Button>
          <span className="text-sm text-fg-muted">
            <span className="mono text-fg">{activeCount}</span> active after saving
          </span>
          {termsDirty ? (
            <Button
              variant="ghost"
              disabled={pendingTerms}
              onClick={() => {
                setRemoved(terms.removed);
                setAdded(terms.added);
              }}
            >
              Discard
            </Button>
          ) : null}
        </div>
        <div className="mt-3">
          <FeedbackNotice feedback={termsFeedback} />
        </div>
      </Card>

      <Card>
        <CardHeader title="Allowed words" description="Words that never count here, even if they're on the list — sigma in a maths server, say." />
        <ChipInput
          label="Allowlist"
          values={allowed}
          onChange={setAllowed}
          placeholder="a word, Enter to add"
          disabled={pendingAllow}
          limit={defaults.limits.custom_terms}
          minLength={defaults.limits.term_length.min}
          maxLength={defaults.limits.term_length.max}
        />
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <Button variant="primary" pending={pendingAllow} disabled={!allowDirty} onClick={() => startAllow(async () => reportAllow(await saveAllowlist(guildId, allowed)))}>
            Save allowlist
          </Button>
          {allowDirty ? (
            <Button variant="ghost" disabled={pendingAllow} onClick={() => setAllowed(terms.allowed)}>
              Discard
            </Button>
          ) : null}
        </div>
        <div className="mt-3">
          <FeedbackNotice feedback={allowFeedback} />
        </div>
      </Card>
    </div>
  );
}
