/** Shallow health for the Docker HEALTHCHECK: the process is up. Never calls the bot. */
export function GET() {
  return Response.json({ ok: true, service: "sprok-dashboard" }, { headers: { "Cache-Control": "no-store" } });
}
