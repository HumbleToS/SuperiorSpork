"use client";

import { useState, useTransition } from "react";
import { setEnabled } from "@/app/(dashboard)/g/[guildId]/brainrot/actions";
import { Button } from "@/components/ui/button";
import { Toggle } from "@/components/ui/toggle";
import { FeedbackNotice, useFeedback } from "./feedback";

export function EnableToggle({ guildId, enabled, ready }: { guildId: string; enabled: boolean; ready: boolean }) {
  const [pending, start] = useTransition();
  const [feedback, report] = useFeedback();
  const [confirming, setConfirming] = useState(false);

  function apply(next: boolean) {
    setConfirming(false);
    start(async () => report(await setEnabled(guildId, next)));
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="font-medium">{enabled ? "Anti-brainrot is on" : "Anti-brainrot is off"}</p>
          <p className="text-sm text-fg-muted">
            {enabled ? "Messages in watched channels are scored." : ready ? "Turn it on to start scoring watched channels." : "Fix the problems below, then turn it on."}
          </p>
        </div>
        <Toggle
          label="Anti-brainrot"
          checked={enabled}
          disabled={pending || (!enabled && !ready)}
          onChange={(next) => (next ? apply(true) : setConfirming(true))}
        />
      </div>
      {confirming ? (
        <div role="group" aria-label="Confirm turning off" className="flex flex-wrap items-center gap-2 rounded-[var(--radius-control)] border border-border bg-surface-2 px-3 py-2 text-sm">
          <span className="text-fg-muted">Turn anti-brainrot off? Settings and the leaderboard are kept.</span>
          <Button size="sm" variant="danger" pending={pending} onClick={() => apply(false)}>
            Turn off
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
            Keep it on
          </Button>
        </div>
      ) : null}
      <FeedbackNotice feedback={feedback} />
    </div>
  );
}
