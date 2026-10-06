"use client";

import { useId, useMemo, useState, useTransition } from "react";
import { saveExemptions } from "@/app/(dashboard)/g/[guildId]/brainrot/actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Rail } from "@/components/ui/rail";
import { Input } from "@/components/ui/field";
import type { Exemptions, MemberRef, Role } from "@/lib/bot/schemas";
import { FeedbackNotice, useFeedback } from "./feedback";
import { MemberSearch } from "./member-search";

type PickedUser = { id: string; name: string | null; avatar: string | null; exists: boolean };

export function ExemptionsEditor({ guildId, roles, exemptions, limit }: { guildId: string; roles: Role[]; exemptions: Exemptions; limit: number }) {
  const [roleIds, setRoleIds] = useState<Set<string>>(() => new Set(exemptions.roles.map((role) => role.id)));
  const [users, setUsers] = useState<PickedUser[]>(exemptions.users);
  const [roleQuery, setRoleQuery] = useState("");
  const [pending, start] = useTransition();
  const [feedback, report] = useFeedback();
  const roleSearchId = useId();

  const savedRoles = useMemo(() => new Set(exemptions.roles.map((role) => role.id)), [exemptions.roles]);
  const savedUsers = useMemo(() => exemptions.users.map((user) => user.id), [exemptions.users]);
  const [seen, setSeen] = useState(exemptions);
  if (seen !== exemptions) {
    // fresh data from the server (after a save, or someone else's change): adopt it
    setSeen(exemptions);
    setRoleIds(new Set(savedRoles));
    setUsers(exemptions.users);
  }
  const dirty = roleIds.size !== savedRoles.size || [...roleIds].some((id) => !savedRoles.has(id)) || users.length !== savedUsers.length || users.some((user) => !savedUsers.includes(user.id));

  const visibleRoles = useMemo(() => {
    const wanted = roleQuery.trim().toLowerCase();
    return [...roles]
      .filter((role) => !role.everyone && (!wanted || role.name.toLowerCase().includes(wanted)))
      .sort((a, b) => b.position - a.position);
  }, [roles, roleQuery]);
  const goneRoles = exemptions.roles.filter((role) => !role.exists);

  function toggleRole(id: string, on: boolean) {
    setRoleIds((current) => {
      const next = new Set(current);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  function pick(member: MemberRef) {
    if (users.some((user) => user.id === member.id) || users.length >= limit) return;
    setUsers((current) => [...current, { id: member.id, name: member.name ?? member.username, avatar: member.avatar, exists: true }]);
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader title="Roles" description={`Members with any of these roles are never scored. Up to ${limit}.`} />
        <div className="mb-3 flex flex-col gap-1.5 sm:max-w-sm">
          <label htmlFor={roleSearchId} className="text-sm font-medium">
            Find a role
          </label>
          <Input id={roleSearchId} type="search" value={roleQuery} onChange={(event) => setRoleQuery(event.target.value)} placeholder="staff, regulars…" autoComplete="off" />
        </div>
        <ul className="card max-h-80 divide-y divide-border overflow-y-auto p-0">
          {visibleRoles.length === 0 ? <li className="px-4 py-6 text-center text-sm text-fg-muted">No roles match.</li> : null}
          {visibleRoles.map((role) => {
            const on = roleIds.has(role.id);
            const full = !on && roleIds.size >= limit;
            return (
              <li key={role.id}>
                <label className={`flex cursor-pointer items-center gap-3 px-4 py-2 text-sm hover:bg-surface-2 ${full ? "opacity-50" : ""}`}>
                  <input type="checkbox" checked={on} disabled={full || pending} onChange={(event) => toggleRole(role.id, event.target.checked)} className="size-4 accent-[var(--accent)]" />
                  <Rail color={role.color} className="h-4 w-1 rounded-full" />
                  <span className="min-w-0 flex-1 truncate">{role.name}</span>
                  {role.managed ? <Badge tone="neutral">managed</Badge> : null}
                </label>
              </li>
            );
          })}
        </ul>
        {goneRoles.length > 0 ? (
          <p className="mt-3 text-sm text-fg-muted">
            {goneRoles.length} exempt role{goneRoles.length === 1 ? " no longer exists" : "s no longer exist"} — saving drops {goneRoles.length === 1 ? "it" : "them"}.
          </p>
        ) : null}
      </Card>

      <Card>
        <CardHeader title="Members" description={`Specific people the heat system leaves alone. Up to ${limit}.`} />
        {users.length > 0 ? (
          <ul className="mb-4 flex flex-wrap gap-1.5" aria-label="Exempt members">
            {users.map((user) => (
              <li key={user.id} className="inline-flex items-center gap-1.5 rounded-[var(--radius-control)] border border-border bg-surface-2 py-0.5 pr-1 pl-1 text-sm">
                {user.avatar ? (
                  // eslint-disable-next-line @next/next/no-img-element -- Discord CDN avatar
                  <img src={user.avatar} alt="" className="size-5 rounded-full" />
                ) : (
                  <span className="size-5 rounded-full bg-surface-3" aria-hidden="true" />
                )}
                <span>{user.name ?? <span className="mono">{user.id}</span>}</span>
                {!user.exists ? <Badge tone="danger">left</Badge> : null}
                <button type="button" aria-label={`Remove ${user.name ?? user.id}`} disabled={pending} onClick={() => setUsers((current) => current.filter((candidate) => candidate.id !== user.id))} className="flex size-5 items-center justify-center rounded-[3px] text-fg-muted hover:bg-surface-3 hover:text-fg">
                  ×
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mb-4 text-sm text-fg-faint">Nobody yet.</p>
        )}
        <MemberSearch guildId={guildId} onPick={pick} exclude={users.map((user) => user.id)} />
        <p className="mt-3 text-sm text-fg-faint">
          Moderators (Administrator, Manage Server, Manage Messages, Moderate Members) are {exemptions.include_mods ? "included — change that in Settings" : "exempt by default; Settings can include them"}.
        </p>
      </Card>

      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" pending={pending} disabled={!dirty} onClick={() => start(async () => report(await saveExemptions(guildId, { role_ids: [...roleIds], user_ids: users.map((user) => user.id) })))}>
          Save exemptions
        </Button>
        {dirty ? (
          <Button
            variant="ghost"
            disabled={pending}
            onClick={() => {
              setRoleIds(new Set(savedRoles));
              setUsers(exemptions.users);
            }}
          >
            Discard changes
          </Button>
        ) : null}
      </div>
      <FeedbackNotice feedback={feedback} />
    </div>
  );
}
