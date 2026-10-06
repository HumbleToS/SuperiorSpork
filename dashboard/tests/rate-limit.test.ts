import { beforeEach, describe, expect, it } from "vitest";
import { _resetForTests, take } from "@/lib/rate-limit";

describe("rate limit", () => {
  beforeEach(() => _resetForTests());

  it("allows up to max in the window then refuses with a retry hint", () => {
    const limit = { max: 3, windowMs: 1000 };
    expect(take("k", limit, 0).ok).toBe(true);
    expect(take("k", limit, 10).ok).toBe(true);
    expect(take("k", limit, 20).ok).toBe(true);
    const refused = take("k", limit, 30);
    expect(refused.ok).toBe(false);
    expect(refused.retryAfterMs).toBe(970);
    expect(take("k", limit, 1001).ok).toBe(true); // the first one slid out
    expect(take("other", limit, 30).ok).toBe(true); // keys are independent
  });
});
