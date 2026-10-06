"use client";

import { useId, useMemo, useState, useTransition } from "react";
import { updateConfig } from "@/app/(dashboard)/g/[guildId]/brainrot/actions";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Field, Input, Select } from "@/components/ui/field";
import { Toggle } from "@/components/ui/toggle";
import type { BrainrotConfig, BrainrotConfigPatch, BrainrotDefaults, Channel, Role } from "@/lib/bot/schemas";
import { formatDuration, parseDuration } from "@/lib/format";
import { FeedbackNotice, useFeedback } from "./feedback";

type Draft = {
  mute_mode: "timeout" | "role";
  mute_role_id: string;
  mute: string;
  ladder: string;
  warnings: string;
  delete_messages: boolean;
  include_mods: boolean;
  modlog_channel_id: string;
};

function draftFrom(config: BrainrotConfig): Draft {
  return {
    mute_mode: config.mute_mode,
    mute_role_id: config.mute_role_id ?? "",
    mute: formatDuration(config.mute_seconds),
    ladder: config.ladder_seconds.map(formatDuration).join(" "),
    warnings: config.warn_delete_seconds === 0 ? "0" : formatDuration(config.warn_delete_seconds),
    delete_messages: config.delete_messages,
    include_mods: config.include_mods,
    modlog_channel_id: config.modlog_channel_id ?? "",
  };
}

/** Every knob, entered as people say it ("5m", "30m 2h 24h"), converted to seconds for the bot. */
export function SettingsForm({ guildId, config, defaults, channels, roles }: { guildId: string; config: BrainrotConfig; defaults: BrainrotDefaults; channels: Channel[]; roles: Role[] }) {
  const [draft, setDraft] = useState<Draft>(() => draftFrom(config));
  const [pending, start] = useTransition();
  const [feedback, report] = useFeedback();
  const [seen, setSeen] = useState(config);
  if (seen !== config) {
    // fresh data from the server (after a save, or someone else's change): adopt it
    setSeen(config);
    setDraft(draftFrom(config));
  }
  const ids = { mode: useId(), role: useId(), mute: useId(), ladder: useId(), warnings: useId(), modlog: useId(), del: useId(), mods: useId() };

  const parsed = useMemo(() => {
    const errors: Partial<Record<keyof Draft, string>> = {};
    const patch: BrainrotConfigPatch = {};
    const max = defaults.limits.max_timeout_seconds;

    if (draft.mute_mode !== config.mute_mode || (draft.mute_mode === "role" && draft.mute_role_id !== (config.mute_role_id ?? ""))) {
      patch.mute_mode = draft.mute_mode;
      if (draft.mute_mode === "role") {
        if (!draft.mute_role_id) errors.mute_role_id = "Pick the muted role.";
        else patch.mute_role_id = draft.mute_role_id;
      }
    }

    const mute = parseDuration(draft.mute);
    if (mute === null || mute < defaults.limits.mute_seconds.min || mute > max || mute % 60 !== 0) {
      errors.mute = `Whole minutes, from 1m to ${formatDuration(max)}.`;
    } else if (mute !== config.mute_seconds) patch.mute_seconds = mute;

    const steps = draft.ladder.split(/[,\s]+/).filter(Boolean).map(parseDuration);
    if (steps.length === 0 || steps.length > defaults.limits.ladder_steps || steps.some((step) => step === null || step < 60 || step > max)) {
      errors.ladder = `1 to ${defaults.limits.ladder_steps} steps like "30m 2h 24h", each 1m to ${formatDuration(max)}.`;
    } else {
      const ladder = steps as number[];
      if (ladder.length !== config.ladder_seconds.length || ladder.some((step, index) => step !== config.ladder_seconds[index])) patch.ladder_seconds = ladder;
    }

    const warnings = draft.warnings.trim() === "0" ? 0 : draft.warnings.trim() === "" ? null : (parseDuration(draft.warnings.replace(/^(\d+)$/, "$1s")) ?? null);
    if (warnings === null || warnings > defaults.limits.warn_delete_seconds.max) {
      errors.warnings = `0 keeps warnings; otherwise up to ${defaults.limits.warn_delete_seconds.max}s (like "30s" or "2m").`;
    } else if (warnings !== config.warn_delete_seconds) patch.warn_delete_seconds = warnings;

    if (draft.delete_messages !== config.delete_messages) patch.delete_messages = draft.delete_messages;
    if (draft.include_mods !== config.include_mods) patch.include_mods = draft.include_mods;
    const modlog = draft.modlog_channel_id || null;
    if (modlog !== config.modlog_channel_id) patch.modlog_channel_id = modlog;

    return { errors, patch, dirty: Object.keys(patch).length > 0 || Object.keys(errors).length > 0 };
  }, [draft, config, defaults]);

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((current) => ({ ...current, [key]: value }));
  const textChannels = channels.filter((channel) => channel.type === "text" || channel.type === "announcement");
  const assignable = [...roles].filter((role) => role.assignable).sort((a, b) => b.position - a.position);
  const canSave = parsed.dirty && Object.keys(parsed.errors).length === 0;

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader title="Punishment" description="What a full heat bar means, and how repeat offenders climb." />
        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="Mute mode" htmlFor={ids.mode} help="Timeout uses Discord's built-in timeout. Role mode hands out a muted role instead; repeat offenders always get a timeout.">
            <Select id={ids.mode} value={draft.mute_mode} onChange={(event) => set("mute_mode", event.target.value === "role" ? "role" : "timeout")} disabled={pending}>
              <option value="timeout">Timeout</option>
              <option value="role">Muted role</option>
            </Select>
          </Field>
          {draft.mute_mode === "role" ? (
            <Field label="Muted role" htmlFor={ids.role} error={parsed.errors.mute_role_id} help="Only roles below the bot's top role are listed.">
              <Select id={ids.role} value={draft.mute_role_id} onChange={(event) => set("mute_role_id", event.target.value)} disabled={pending}>
                <option value="">Pick a role…</option>
                {assignable.map((role) => (
                  <option key={role.id} value={role.id}>
                    {role.name}
                  </option>
                ))}
              </Select>
            </Field>
          ) : null}
          <Field label="Mute duration" htmlFor={ids.mute} error={parsed.errors.mute} help="How long a full bar keeps someone quiet. Whole minutes: 5m, 30m, 2h.">
            <Input id={ids.mute} value={draft.mute} onChange={(event) => set("mute", event.target.value)} disabled={pending} inputMode="text" className="mono" />
          </Field>
          <Field label="Repeat ladder" htmlFor={ids.ladder} error={parsed.errors.ladder} help="Timeouts for offenses within 7 days of a mute, in order. Up to 5 steps, 28 days max.">
            <Input id={ids.ladder} value={draft.ladder} onChange={(event) => set("ladder", event.target.value)} disabled={pending} placeholder="30m 2h 24h" className="mono" />
          </Field>
        </div>
      </Card>

      <Card>
        <CardHeader title="Warnings and messages" />
        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="Warnings stay for" htmlFor={ids.warnings} error={parsed.errors.warnings} help="Warnings delete themselves after this. 0 keeps them in chat.">
            <Input id={ids.warnings} value={draft.warnings} onChange={(event) => set("warnings", event.target.value)} disabled={pending} placeholder="30s" className="mono" />
          </Field>
          <div className="flex flex-col gap-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <label htmlFor={ids.del} className="text-sm font-medium">
                  Delete offending messages
                </label>
                <p className="text-sm text-fg-faint">Needs Manage Messages in each watched channel.</p>
              </div>
              <Toggle id={ids.del} label="Delete offending messages" checked={draft.delete_messages} onChange={(next) => set("delete_messages", next)} disabled={pending} />
            </div>
            <div className="flex items-start justify-between gap-4">
              <div>
                <label htmlFor={ids.mods} className="text-sm font-medium">
                  Moderators get heat too
                </label>
                <p className="text-sm text-fg-faint">Off means Administrator, Manage Server, Manage Messages, and Moderate Members are exempt.</p>
              </div>
              <Toggle id={ids.mods} label="Moderators get heat too" checked={draft.include_mods} onChange={(next) => set("include_mods", next)} disabled={pending} />
            </div>
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader title="Mod log" description="Mutes, timeouts, pardons, and settings changed here are posted to this channel." />
        <Field label="Channel" htmlFor={ids.modlog}>
          <Select id={ids.modlog} value={draft.modlog_channel_id} onChange={(event) => set("modlog_channel_id", event.target.value)} disabled={pending} className="sm:max-w-sm">
            <option value="">Off</option>
            {textChannels.map((channel) => (
              <option key={channel.id} value={channel.id}>
                #{channel.name}
                {channel.category ? ` · ${channel.category.name}` : ""}
              </option>
            ))}
          </Select>
        </Field>
      </Card>

      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" pending={pending} disabled={!canSave} onClick={() => start(async () => report(await updateConfig(guildId, parsed.patch)))}>
          Save settings
        </Button>
        {parsed.dirty ? (
          <Button variant="ghost" disabled={pending} onClick={() => setDraft(draftFrom(config))}>
            Discard changes
          </Button>
        ) : null}
      </div>
      <FeedbackNotice feedback={feedback} />
    </div>
  );
}
