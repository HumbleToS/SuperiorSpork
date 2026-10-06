import { EncryptJWT, base64url } from "jose";

export const SECRET = "c2Vzc2lvbi1zZWNyZXQtZm9yLXRlc3RzLTMyLWJ5dGVzISE";
export const GUILD = "100000000000000100";
export const USER = "100000000000000004";

/** The same JWE the app writes, so a test can be signed in without Discord. */
export async function sessionCookie(): Promise<string> {
  const key = base64url.decode(SECRET).subarray(0, 32);
  const expiresAt = Math.floor(Date.now() / 1000) + 3600;
  return new EncryptJWT({ userId: USER, username: "jaden", displayName: "Jaden", avatar: null, accessToken: "x", expiresAt })
    .setProtectedHeader({ alg: "dir", enc: "A256GCM" })
    .setIssuer("sprok-dashboard")
    .setIssuedAt()
    .setExpirationTime(expiresAt)
    .encrypt(key);
}
