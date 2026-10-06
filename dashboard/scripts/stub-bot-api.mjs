// A stand-in for the bot's internal API (docs/internal-api.md in the bot repo) so the dashboard runs
// locally without the bot. Same envelope, same shapes, same refusals for the obvious mistakes. In memory.
//
//   BOT_API_TOKEN=dev-token pnpm stub:bot            # listens on 127.0.0.1:8080
//   BOT_API_URL=http://127.0.0.1:8080/internal/v1 BOT_API_TOKEN=dev-token pnpm dev

import http from "node:http";

const PORT = Number(process.env.STUB_PORT ?? 8080);
const TOKEN = process.env.BOT_API_TOKEN ?? "dev-token";
/** The Discord user id the stub treats as a manager; set it to your own to click through. */
const MANAGER = process.env.STUB_MANAGER_ID ?? "*";
const GUILD_ID = "100000000000000100";
const now = () => new Date().toISOString();

const defaults = {
  default_terms: ["skibidi", "gyat", "rizz", "rizzler", "sigma", "fanum tax", "mewing", "delulu", "bussin", "sussy", "griddy", "goofy ahh", "only in ohio"],
  tiers: [
    { min_offenses: 0, title: "Raw" },
    { min_offenses: 1, title: "Lightly Seared" },
    { min_offenses: 5, title: "Medium" },
    { min_offenses: 15, title: "Well Done" },
    { min_offenses: 30, title: "Cooked" },
    { min_offenses: 60, title: "Burnt" },
    { min_offenses: 100, title: "Charcoal" },
  ],
  max_heat: 5,
  decay_seconds: 3600,
  window_seconds: 30,
  window_cap: 3,
  spam_hits: 4,
  repeat_days: 7,
  mute_modes: ["timeout", "role"],
  limits: {
    channels: 50,
    custom_terms: 100,
    exemptions: 50,
    term_length: { min: 3, max: 40 },
    ladder_steps: 5,
    mute_seconds: { min: 60, max: 2419200 },
    warn_delete_seconds: { min: 0, max: 600 },
    max_timeout_seconds: 2419200,
  },
};

const tier = (n) => defaults.tiers.reduce((title, t) => (n >= t.min_offenses ? t.title : title), "Raw");

const state = {
  config: {
    enabled: true,
    mute_mode: "timeout",
    mute_role_id: null,
    mute_seconds: 300,
    ladder_seconds: [1800, 7200, 86400],
    warn_delete_seconds: 30,
    delete_messages: false,
    include_mods: false,
    modlog_channel_id: "100000000000000201",
  },
  channels: ["100000000000000200"],
  added: ["ohio"],
  removed: [],
  allowed: ["sigma"],
  exemptRoles: ["100000000000000302"],
  exemptUsers: [],
  users: new Map([
    ["100000000000000004", { name: "user", heat: 3, lifetime: 17, repeat: true, level: 1 }],
    ["100000000000000005", { name: "exempt", heat: 0, lifetime: 41, repeat: false, level: 0 }],
    ["100000000000000003", { name: "mod", heat: 1, lifetime: 2, repeat: false, level: 0 }],
  ]),
  actions: [],
};

const channels = [
  { id: "100000000000000200", name: "general", type: "text", position: 0, category: { id: "100000000000000210", name: "Chat" } },
  { id: "100000000000000201", name: "mod-log", type: "text", position: 1, category: { id: "100000000000000211", name: "Staff" } },
  { id: "100000000000000202", name: "voice-chat", type: "voice", position: 2, category: null },
  { id: "100000000000000203", name: "help", type: "forum", position: 3, category: { id: "100000000000000210", name: "Chat" } },
];
const roles = [
  { id: GUILD_ID, name: "@everyone", color: null, position: 0, managed: false, everyone: true, assignable: false },
  { id: "100000000000000302", name: "exempt", color: "#f5b84a", position: 1, managed: false, everyone: false, assignable: true },
  { id: "100000000000000303", name: "muted", color: "#6f727e", position: 2, managed: false, everyone: false, assignable: true },
  { id: "100000000000000301", name: "mods", color: "#6ea8fe", position: 3, managed: false, everyone: false, assignable: true },
  { id: "100000000000000300", name: "sprok", color: "#10b981", position: 4, managed: true, everyone: false, assignable: false },
];

const commands = {
  prefix: ",,",
  categories: [
    {
      name: "Brainrot",
      blurb: "Heat, mutes, and the leaderboard for brainrot vocabulary",
      emoji: null,
      commands: [
        cmd("brainrot pardon", "Clears someone's heat, repeat flag, and any mute I applied", "/brainrot pardon <member> [amount]", "/brainrot pardon member:@someone", ["Moderate Members"]),
        cmd("brainrot score", "Shows someone's heat, repeat status, and lifetime offenses", "/brainrot score [member]", "/brainrot score member:@someone", [], "1 every 5 seconds"),
        cmd("brainrot leaderboard", "The server's most cooked members, by lifetime offenses", "/brainrot leaderboard", "/brainrot leaderboard", [], "1 every 5 seconds"),
        cmd("brainrot enable", "Turns anti-brainrot on, after checking I have what I need", "/brainrot enable", "/brainrot enable", ["Manage Server"]),
      ],
    },
    {
      name: "General",
      blurb: "Server, user, and bot info",
      emoji: null,
      commands: [
        cmd("whois", "Shows information about a user", "/whois [member]", "/whois member:@someone", [], null, false),
        cmd("serverinfo", "Shows information about the server", "/serverinfo", "/serverinfo", [], null, true),
        { ...cmd("cleanup", "Deletes my messages and the commands that called them", ",,cleanup [amount=25]", ",,cleanup 25", ["Manage Messages"]), slash: false, shown_name: ",,cleanup" },
      ],
    },
  ],
};

function cmd(name, description, usage, example, permissions = [], cooldown = null, guild_only = true) {
  return { name, shown_name: `/${name}`, description, details: description, usage, example, permissions, guild_only, cooldown, slash: true, slash_id: null };
}

const config = () => ({
  ...state.config,
  ready: true,
  problems: [],
  counts: {
    channels: state.channels.length,
    terms: defaults.default_terms.length + state.added.length - state.removed.length - state.allowed.length,
    added: state.added.length,
    removed: state.removed.length,
    allowed: state.allowed.length,
    exempt_roles: state.exemptRoles.length,
    exempt_users: state.exemptUsers.length,
  },
});

const active = () => [...defaults.default_terms.filter((t) => !state.removed.includes(t) && !state.allowed.includes(t)), ...state.added.filter((t) => !state.allowed.includes(t))];
const member = (id) => ({ id, name: state.users.get(id)?.name ?? null, username: state.users.get(id)?.name ?? null, avatar: null, bot: false });
const channelsList = () => ({ channels: state.channels.map((id) => ({ id, name: channels.find((c) => c.id === id)?.name ?? null, type: channels.find((c) => c.id === id)?.type ?? null, exists: channels.some((c) => c.id === id) })) });
const exemptions = () => ({
  roles: state.exemptRoles.map((id) => ({ id, name: roles.find((r) => r.id === id)?.name ?? null, color: roles.find((r) => r.id === id)?.color ?? null, exists: roles.some((r) => r.id === id) })),
  users: state.exemptUsers.map((id) => ({ id, name: state.users.get(id)?.name ?? null, avatar: null, exists: state.users.has(id) })),
  include_mods: state.config.include_mods,
});
const termsLists = () => ({ active: active(), defaults: defaults.default_terms, added: state.added, removed: state.removed, allowed: state.allowed });

function log(action, source, fields) {
  state.actions.unshift({ id: String(state.actions.length + 1), at: now(), action, source, applied: true, target: null, actor: null, heat: null, heat_added: null, duration_seconds: null, escalation_level: null, field: null, before: null, after: null, ...fields });
}
log("warning", "auto", { target: member("100000000000000004"), heat: 1, heat_added: 1 });
log("mute", "auto", { target: member("100000000000000004"), heat: 5, heat_added: 1, duration_seconds: 300 });
log("pardon", "command", { target: member("100000000000000005"), actor: member("100000000000000003"), heat: 0, heat_added: -2 });

const ok = (res, data, extra = {}) => send(res, 200, { ok: true, data, ...extra });
const fail = (res, status, code, message, extra = {}) => send(res, status, { ok: false, error: { code, message, ...extra } });
function send(res, status, body) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
}
function paged(res, items, query) {
  const page = Math.max(1, Number(query.get("page") ?? 1));
  const per = Math.min(100, Math.max(1, Number(query.get("per_page") ?? 25)));
  const start = (page - 1) * per;
  ok(res, items.slice(start, start + per), { page: { page, per_page: per, total: items.length, pages: Math.max(1, Math.ceil(items.length / per)) } });
}
async function body(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return chunks.length ? JSON.parse(Buffer.concat(chunks).toString()) : {};
}

const server = http.createServer(async (req, res) => {
  if (req.headers.authorization !== `Bearer ${TOKEN}`) {
    res.writeHead(401);
    return res.end();
  }
  const url = new URL(req.url ?? "/", "http://stub");
  const path = url.pathname.replace(/^\/internal\/v1/, "");
  const user = req.headers["x-acting-user-id"] ?? url.searchParams.get("user_id");
  const manages = MANAGER === "*" || user === MANAGER;
  const guildPath = path.match(/^\/guilds\/(\d+)(\/.*)?$/);

  if (path === "/health") return ok(res, { ready: true, latency_ms: 42, guilds: 1 });
  if (path === "/app") return ok(res, { application_id: "100000000000000001", permissions: "1099780063302", invite_url: "https://discord.com/oauth2/authorize?client_id=100000000000000001&scope=bot%20applications.commands&permissions=1099780063302", prefix: ",," });
  if (path === "/commands") return ok(res, commands);
  if (path === "/brainrot/defaults") return ok(res, defaults);
  if (path === "/guilds") {
    if (!user) return fail(res, 400, "bad_request", "X-Acting-User-Id is required.");
    return ok(res, manages ? [{ id: GUILD_ID, name: "The Kitchen", icon: null, accent: "#f2d9c0", owner: true }] : []);
  }
  if (!guildPath) return fail(res, 404, "not_found", "Not Found");
  if (!user) return fail(res, 400, "bad_request", "X-Acting-User-Id is required.");
  if (guildPath[1] !== GUILD_ID) return fail(res, 404, "guild_not_found", "I'm not in that server.");
  if (!manages) return fail(res, 403, "forbidden", "You need Manage Server in that server.");
  const tail = guildPath[2] ?? "";

  if (tail === "/meta") {
    return ok(res, {
      id: GUILD_ID, name: "The Kitchen", icon: null, accent: "#f2d9c0", owner_id: user, channels, roles,
      me: { top_role_id: "100000000000000300", permissions: { view_channel: true, send_messages: true, embed_links: true, manage_messages: true, moderate_members: true, manage_roles: true, read_message_history: true } },
      brainrot: { ready: true, problems: [] },
    });
  }
  if (tail === "/members/search") {
    const q = (url.searchParams.get("q") ?? "").toLowerCase();
    return ok(res, [...state.users.keys()].filter((id) => id.includes(q) || state.users.get(id).name.includes(q)).map(member));
  }
  const one = tail.match(/^\/members\/(\d+)$/);
  if (one) return state.users.has(one[1]) ? ok(res, member(one[1])) : fail(res, 404, "not_found", "That user isn't in this server.", { field: "user_id" });

  if (tail === "/brainrot/config" && req.method === "GET") return ok(res, config());
  if (tail === "/brainrot/config" && req.method === "PATCH") {
    const patch = await body(req);
    if (patch.mute_seconds !== undefined && (patch.mute_seconds < 60 || patch.mute_seconds % 60)) return fail(res, 422, "invalid", "A full-bar mute lasts 1 to 40,320 whole minutes.", { field: "mute_seconds" });
    if (patch.mute_mode === "role" && !(patch.mute_role_id ?? state.config.mute_role_id)) return fail(res, 422, "invalid", "Role mode needs a muted role.", { field: "mute_role_id" });
    for (const [key, value] of Object.entries(patch)) {
      if (!(key in state.config)) return fail(res, 400, "bad_request", `Unknown settings: ${key}.`, { field: key });
      if (state.config[key] !== value) log("config", "dashboard", { actor: member(user), field: key, before: String(state.config[key]), after: String(value) });
      state.config[key] = value;
    }
    return ok(res, config());
  }
  if (tail === "/brainrot/channels" && req.method === "GET") return ok(res, channelsList());
  if (tail === "/brainrot/channels" && req.method === "PUT") {
    const wanted = (await body(req)).channel_ids ?? [];
    const unknown = wanted.find((id) => !channels.some((c) => c.id === id));
    state.channels = wanted.filter((id) => channels.some((c) => c.id === id));
    if (unknown) return send(res, 404, { ok: false, error: { code: "not_found", message: "That channel isn't in this server.", field: "channel_ids" }, data: channelsList() });
    return ok(res, channelsList());
  }
  if (tail === "/brainrot/terms" && req.method === "GET") return ok(res, termsLists());
  if (tail === "/brainrot/terms" && req.method === "PUT") {
    const { added = state.added, removed = state.removed } = await body(req);
    const bad = added.find((t) => t.length < 3 || t.length > 40);
    state.removed = removed.filter((t) => defaults.default_terms.includes(t));
    state.added = added.filter((t) => t.length >= 3 && t.length <= 40).map((t) => t.toLowerCase());
    if (bad) return send(res, 422, { ok: false, error: { code: "invalid", message: "Terms need to be 3 to 40 characters.", field: "added" }, data: termsLists() });
    return ok(res, termsLists());
  }
  if (tail === "/brainrot/allowlist" && req.method === "GET") return ok(res, { allowed: state.allowed });
  if (tail === "/brainrot/allowlist" && req.method === "PUT") {
    state.allowed = ((await body(req)).allowed ?? []).map((t) => t.toLowerCase());
    return ok(res, { allowed: state.allowed });
  }
  if (tail === "/brainrot/exemptions" && req.method === "GET") return ok(res, exemptions());
  if (tail === "/brainrot/exemptions" && req.method === "PUT") {
    const { role_ids = state.exemptRoles, user_ids = state.exemptUsers } = await body(req);
    const missing = user_ids.find((id) => !state.users.has(id));
    state.exemptRoles = role_ids.filter((id) => roles.some((r) => r.id === id));
    state.exemptUsers = user_ids.filter((id) => state.users.has(id));
    if (missing) return send(res, 404, { ok: false, error: { code: "not_found", message: "That user isn't in this server.", field: "user_id" }, data: exemptions() });
    return ok(res, exemptions());
  }
  if (tail === "/brainrot/summary") {
    const users = [...state.users.values()];
    return ok(res, { enabled: state.config.enabled, watched_channels: state.channels.length, hot_users: users.filter((u) => u.heat > 0).length, muted_now: 0, on_repeat_list: users.filter((u) => u.repeat).length, lifetime_offenses: users.reduce((s, u) => s + u.lifetime, 0), actions_24h: state.actions.length });
  }
  if (tail === "/brainrot/offenders") {
    const sort = url.searchParams.get("sort") ?? "heat";
    const rows = [...state.users.entries()]
      .map(([id, u]) => ({ id, ...u }))
      .sort((a, b) => (sort === "lifetime" ? b.lifetime - a.lifetime : b.heat - a.heat || b.lifetime - a.lifetime));
    const ranked = [...state.users.values()].map((u) => u.lifetime).sort((a, b) => b - a);
    return paged(res, rows.map((u) => ({
      user_id: u.id, name: u.name, avatar: null, in_guild: true, heat: u.heat, max_heat: 5,
      cooling_at: u.heat > 0 ? new Date(Date.now() + 1800e3).toISOString() : null, repeat: u.repeat,
      repeat_until: u.repeat ? new Date(Date.now() + 5 * 86400e3).toISOString() : null, escalation_level: u.level,
      lifetime_offenses: u.lifetime, title: tier(u.lifetime), rank: u.lifetime ? ranked.indexOf(u.lifetime) + 1 : null, muted_until: null,
    })), url.searchParams);
  }
  if (tail === "/brainrot/pardon" && req.method === "POST") {
    const { user_id, amount = 0 } = await body(req);
    const target = state.users.get(user_id);
    if (!target) return fail(res, 404, "not_found", "That user isn't in this server.", { field: "user_id" });
    target.heat = amount ? Math.max(0, target.heat - amount) : 0;
    if (!amount) target.repeat = false;
    log("pardon", "dashboard", { target: member(user_id), actor: member(user), heat: target.heat });
    return ok(res, { user_id, heat: target.heat, repeat: target.repeat, lifted_mute: false });
  }
  if (tail === "/brainrot/actions") {
    const action = url.searchParams.get("action");
    const source = url.searchParams.get("source");
    return paged(res, state.actions.filter((a) => (!action || a.action === action) && (!source || a.source === source)), url.searchParams);
  }
  return fail(res, 404, "not_found", "Not Found");
});

server.listen(PORT, "127.0.0.1", () => console.log(`stub bot api on http://127.0.0.1:${PORT}/internal/v1 (token: ${TOKEN})`));
