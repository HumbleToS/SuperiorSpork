import { describe, expect, it } from "vitest";
import { describeConfigValue, describeDuration, formatDuration, parseDuration } from "@/lib/format";

describe("durations", () => {
  it("formats compactly", () => {
    expect(formatDuration(0)).toBe("0s");
    expect(formatDuration(600)).toBe("10m");
    expect(formatDuration(5400)).toBe("1h 30m");
    expect(formatDuration(86400 * 2 + 3600)).toBe("2d 1h");
  });

  it("describes in the bot's words", () => {
    expect(describeDuration(300)).toBe("5 minutes");
    expect(describeDuration(60)).toBe("1 minute");
    expect(describeDuration(7200)).toBe("2 hours");
    expect(describeDuration(172800)).toBe("2 days");
  });

  it("parses friendly input to seconds", () => {
    expect(parseDuration("5m")).toBe(300);
    expect(parseDuration("2h")).toBe(7200);
    expect(parseDuration("1d 12h")).toBe(129600);
    expect(parseDuration("90")).toBe(5400);
    expect(parseDuration("")).toBeNull();
    expect(parseDuration("soon")).toBeNull();
    expect(parseDuration("0m")).toBeNull();
  });

  it("renders action-log values by field", () => {
    expect(describeConfigValue("mute_seconds", "300")).toBe("5 minutes");
    expect(describeConfigValue("warn_delete_seconds", "0")).toBe("kept");
    expect(describeConfigValue("ladder_seconds", "1800,7200")).toBe("30 minutes → 2 hours");
    expect(describeConfigValue("enabled", "true")).toBe("on");
    expect(describeConfigValue("added_terms", "ohio")).toBe("ohio");
    expect(describeConfigValue("modlog_channel_id", null)).toBe("—");
  });
});
