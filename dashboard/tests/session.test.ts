import { describe, expect, it } from "vitest";

process.env.SESSION_SECRET = "c2Vzc2lvbi1zZWNyZXQtZm9yLXRlc3RzLTMyLWJ5dGVzISE";
process.env.DISCORD_CLIENT_ID = "100000000000000001";
process.env.DISCORD_CLIENT_SECRET = "secret-secret-secret";
process.env.BOT_API_TOKEN = "token-token-token";

const { openSession, sealSession } = await import("@/lib/auth/session");

describe("session cookie", () => {
  const base = {
    userId: "100000000000000004",
    username: "jaden",
    displayName: "Jaden",
    avatar: null,
    accessToken: "abc",
  };

  it("round-trips through JWE and is opaque", async () => {
    const expiresAt = Math.floor(Date.now() / 1000) + 3600;
    const sealed = await sealSession({ ...base, expiresAt });
    expect(sealed.split(".").length).toBe(5); // compact JWE
    expect(sealed).not.toContain("jaden");
    expect(await openSession(sealed)).toEqual({ ...base, expiresAt });
  });

  it("refuses expired and tampered tokens", async () => {
    const expiresAt = Math.floor(Date.now() / 1000) - 10;
    const sealed = await sealSession({ ...base, expiresAt });
    expect(await openSession(sealed)).toBeNull();
    const fresh = await sealSession({ ...base, expiresAt: expiresAt + 3600 });
    expect(await openSession(`${fresh.slice(0, -4)}AAAA`)).toBeNull();
    expect(await openSession("nonsense")).toBeNull();
  });
});
