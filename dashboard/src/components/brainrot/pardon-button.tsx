"use client";

import { useState, useTransition } from "react";
import { pardonMember } from "@/app/(dashboard)/g/[guildId]/brainrot/actions";
import { Button } from "@/components/ui/button";
import { FeedbackNotice, useFeedback } from "./feedback";

export function PardonButton({ guildId, userId, name, heat }: { guildId: string; userId: string; name: string; heat: number }) {
  const [asking, setAsking] = useState(false);
  const [amount, setAmount] = useState(0);
  const [pending, start] = useTransition();
  const [feedback, report] = useFeedback();

  function run() {
    setAsking(false);
    start(async () => report(await pardonMember(guildId, userId, amount)));
  }

  return (
    <div className="flex flex-col gap-2">
      {asking ? (
        <div role="group" aria-label={`Pardon ${name}`} className="flex flex-wrap items-center gap-2 text-sm">
          <select value={amount} onChange={(event) => setAmount(Number(event.target.value))} aria-label="How much" className="h-8 rounded-md border border-border bg-surface-2 px-2 text-sm">
            <option value={0}>Everything: heat, repeat list, mute</option>
            {Array.from({ length: Math.min(heat, 5) }, (_, index) => index + 1).map((n) => (
              <option key={n} value={n}>
                {n} heat point{n === 1 ? "" : "s"}
              </option>
            ))}
          </select>
          <Button size="sm" variant="primary" pending={pending} onClick={run}>
            Pardon {name}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setAsking(false)} disabled={pending}>
            Cancel
          </Button>
        </div>
      ) : (
        <Button size="sm" pending={pending} onClick={() => setAsking(true)}>
          Pardon
        </Button>
      )}
      <FeedbackNotice feedback={feedback} />
    </div>
  );
}
