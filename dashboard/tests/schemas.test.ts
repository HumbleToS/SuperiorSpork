import { describe, expect, it } from "vitest";
import * as S from "@/lib/bot/schemas";

describe("contract schemas", () => {
  it("accepts python isoformat timestamps with microseconds", () => {
    const action = {
      id: "1",
      at: "2026-09-16T06:01:12.123456+00:00",
      action: "mute",
      source: "auto",
      applied: true,
      target: { id: "100000000000000004", name: "user", username: "user", avatar: null, bot: false },
      actor: null,
      heat: 5,
      heat_added: 1,
      duration_seconds: 300,
      escalation_level: null,
      field: null,
      before: null,
      after: null,
      surprise: "an extra field the bot added later",
    };
    const parsed = S.Action.parse(action);
    expect(parsed.at).toBe(action.at);
    expect("surprise" in parsed).toBe(false);
  });

  it("keeps snowflakes as strings and rejects numbers", () => {
    expect(S.Snowflake.safeParse("100000000000000004").success).toBe(true);
    expect(S.Snowflake.safeParse(100000000000000004).success).toBe(false);
    expect(S.Snowflake.safeParse("abc").success).toBe(false);
  });

  it("validates a config patch before it leaves the server", () => {
    expect(S.BrainrotConfigPatch.safeParse({ mute_seconds: 600 }).success).toBe(true);
    expect(S.BrainrotConfigPatch.safeParse({ mute_seconds: 30 }).success).toBe(false);
    expect(S.BrainrotConfigPatch.safeParse({ ladder_seconds: [] }).success).toBe(false);
    expect(S.BrainrotConfigPatch.safeParse({ warn_delete_seconds: 601 }).success).toBe(false);
    expect(S.BrainrotConfigPatch.safeParse({ modlog_channel_id: null }).success).toBe(true);
  });

  it("parses the failure envelope with partial-state data", () => {
    const failure = S.Failure.parse({ ok: false, error: { code: "limit_reached", message: "That's the limit.", field: "channel_ids" }, data: { channels: [] } });
    expect(failure.error.code).toBe("limit_reached");
    expect(failure.data).toEqual({ channels: [] });
  });
});
