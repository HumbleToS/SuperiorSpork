"use client";

import { useCallback, useEffect, useState } from "react";
import { Notice } from "@/components/ui/notice";
import type { ActionResult } from "@/app/(dashboard)/g/[guildId]/brainrot/actions";

export type Feedback =
  | { status: "idle" }
  | { status: "success"; message: string }
  | { status: "error"; message: string; problems?: string[]; offline?: boolean };

/** One place for the pending → success → error dance every editor does. Success clears itself. */
export function useFeedback(): [Feedback, (result: ActionResult<unknown>) => void, () => void] {
  const [feedback, setFeedback] = useState<Feedback>({ status: "idle" });
  const report = useCallback((result: ActionResult<unknown>) => {
    setFeedback(result.ok ? { status: "success", message: result.message } : { status: "error", message: result.error, problems: result.problems, offline: result.offline });
  }, []);
  const clear = useCallback(() => setFeedback({ status: "idle" }), []);
  useEffect(() => {
    if (feedback.status !== "success") return;
    const timer = setTimeout(() => setFeedback({ status: "idle" }), 4000);
    return () => clearTimeout(timer);
  }, [feedback]);
  return [feedback, report, clear];
}

export function FeedbackNotice({ feedback }: { feedback: Feedback }) {
  return (
    <div aria-live="polite" className="empty:hidden">
      {feedback.status === "success" ? <Notice tone="success">{feedback.message}</Notice> : null}
      {feedback.status === "error" ? (
        <Notice tone={feedback.offline ? "warn" : "error"} title={feedback.message}>
          {feedback.problems?.length ? (
            <ul className="mt-1 flex flex-col gap-0.5">
              {feedback.problems.map((problem) => (
                <li key={problem}>· {problem}</li>
              ))}
            </ul>
          ) : null}
        </Notice>
      ) : null}
    </div>
  );
}
