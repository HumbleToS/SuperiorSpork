"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";
import { requireSession } from "@/lib/auth/require";
import {
  BotApiError,
  BotUnreachableError,
  getMember,
  pardon,
  patchBrainrotConfig,
  putAllowlist,
  putChannels,
  putExemptions,
  putTerms,
  searchMembers,
} from "@/lib/bot/client";
import * as S from "@/lib/bot/schemas";
import { LIMITS, take } from "@/lib/rate-limit";

/**
 * Every anti-brainrot mutation the dashboard can make. Each one: a real session, a per-user rate
 * limit, zod on the input, one call to the bot (which does the actual permission check and the
 * validation the slash commands do), then the page is revalidated. The bot's refusal text is passed
 * through untouched; it is written for the admin.
 */

export type ActionResult<T = undefined> =
  | { ok: true; message: string; data?: T }
  | { ok: false; error: string; field?: string; problems?: string[]; offline?: boolean };

const GuildId = z.string().regex(/^\d{15,22}$/);
const Snowflakes = z.array(S.Snowflake).max(200);
const Words = z.array(z.string().trim().min(1).max(60)).max(200);

async function guarded<T>(guildId: string, work: (userId: string) => Promise<ActionResult<T>>): Promise<ActionResult<T>> {
  const session = await requireSession();
  if (!GuildId.safeParse(guildId).success) return { ok: false, error: "That server id doesn't look right." };
  const limit = take(`mutate:${session.userId}`, LIMITS.mutation);
  if (!limit.ok) {
    return { ok: false, error: `Slow down a little — try again in ${Math.ceil(limit.retryAfterMs / 1000)}s.` };
  }
  try {
    const result = await work(session.userId);
    revalidatePath(`/g/${guildId}/brainrot`, "layout");
    return result;
  } catch (error) {
    if (error instanceof BotApiError) {
      return { ok: false, error: error.message, field: error.field, problems: error.problems.length ? [...error.problems] : undefined };
    }
    if (error instanceof BotUnreachableError) {
      return { ok: false, error: "The bot is unreachable right now, so nothing was changed. Try again in a minute.", offline: true };
    }
    throw error;
  }
}

export async function updateConfig(guildId: string, input: unknown): Promise<ActionResult<S.BrainrotConfig>> {
  const patch = S.BrainrotConfigPatch.safeParse(input);
  if (!patch.success) {
    const issue = patch.error.issues[0];
    return { ok: false, error: issue ? `${issue.path.join(".")}: ${issue.message}` : "Those settings don't look right.", field: issue?.path.join(".") };
  }
  if (Object.keys(patch.data).length === 0) return { ok: true, message: "Nothing to change." };
  return guarded(guildId, async (userId) => {
    const config = await patchBrainrotConfig(guildId, userId, patch.data);
    return { ok: true, message: "Settings saved.", data: config };
  });
}

export async function setEnabled(guildId: string, enabled: boolean): Promise<ActionResult<S.BrainrotConfig>> {
  return guarded(guildId, async (userId) => {
    const config = await patchBrainrotConfig(guildId, userId, { enabled: z.boolean().parse(enabled) });
    return { ok: true, message: enabled ? "Anti-brainrot is on." : "Anti-brainrot is off. Everything is kept.", data: config };
  });
}

export async function saveChannels(guildId: string, input: unknown): Promise<ActionResult<S.ChannelsList>> {
  const ids = Snowflakes.safeParse(input);
  if (!ids.success) return { ok: false, error: "That channel list doesn't look right." };
  return guarded(guildId, async (userId) => {
    const list = await putChannels(guildId, userId, ids.data);
    return { ok: true, message: `Watching ${list.channels.length} channel${list.channels.length === 1 ? "" : "s"}.`, data: list };
  });
}

export async function saveTerms(guildId: string, input: unknown): Promise<ActionResult<S.TermsLists>> {
  const lists = z.object({ added: Words, removed: Words }).safeParse(input);
  if (!lists.success) return { ok: false, error: "Those terms don't look right." };
  return guarded(guildId, async (userId) => {
    const terms = await putTerms(guildId, userId, lists.data);
    return { ok: true, message: `Vocabulary saved — ${terms.active.length} active terms.`, data: terms };
  });
}

export async function saveAllowlist(guildId: string, input: unknown): Promise<ActionResult<S.Allowlist>> {
  const allowed = Words.safeParse(input);
  if (!allowed.success) return { ok: false, error: "That allowlist doesn't look right." };
  return guarded(guildId, async (userId) => {
    const list = await putAllowlist(guildId, userId, allowed.data);
    return { ok: true, message: `Allowlist saved — ${list.allowed.length} word${list.allowed.length === 1 ? "" : "s"}.`, data: list };
  });
}

export async function saveExemptions(guildId: string, input: unknown): Promise<ActionResult<S.Exemptions>> {
  const lists = z.object({ role_ids: Snowflakes, user_ids: Snowflakes }).safeParse(input);
  if (!lists.success) return { ok: false, error: "Those exemptions don't look right." };
  return guarded(guildId, async (userId) => {
    const exemptions = await putExemptions(guildId, userId, lists.data);
    return { ok: true, message: `Exemptions saved — ${exemptions.roles.length} roles, ${exemptions.users.length} members.`, data: exemptions };
  });
}

export async function pardonMember(guildId: string, targetId: string, amount: number): Promise<ActionResult<S.PardonResult>> {
  const input = z.object({ targetId: S.Snowflake, amount: z.number().int().min(0).max(5) }).safeParse({ targetId, amount });
  if (!input.success) return { ok: false, error: "That pardon doesn't look right." };
  return guarded(guildId, async (userId) => {
    const result = await pardon(guildId, userId, input.data.targetId, input.data.amount);
    const message = input.data.amount
      ? `Took ${input.data.amount} off — they're at ${result.heat}/5 now.`
      : `Pardoned — heat cleared, off the repeat list${result.lifted_mute ? ", and unmuted" : ""}.`;
    return { ok: true, message, data: result };
  });
}

/** Reads, not mutations, but they still need a session and they still go through the bot. */
export async function findMembers(guildId: string, query: string): Promise<ActionResult<S.MemberRef[]>> {
  const session = await requireSession();
  const q = z.string().trim().min(1).max(64).safeParse(query);
  if (!q.success || !GuildId.safeParse(guildId).success) return { ok: false, error: "Type at least one character." };
  try {
    const mention = q.data.match(/^<@!?(\d{15,22})>$/);
    const exactId = mention?.[1] ?? (/^\d{15,22}$/.test(q.data) ? q.data : null);
    if (exactId) {
      const member = await getMember(guildId, session.userId, exactId);
      return { ok: true, message: "Found.", data: [member] };
    }
    const members = await searchMembers(guildId, session.userId, q.data);
    return { ok: true, message: `${members.length} found.`, data: members };
  } catch (error) {
    if (error instanceof BotApiError) return { ok: false, error: error.message, field: error.field };
    if (error instanceof BotUnreachableError) return { ok: false, error: "The bot is unreachable right now.", offline: true };
    throw error;
  }
}
