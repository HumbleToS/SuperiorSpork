import { describe, expect, it } from "vitest";
import { filterIndex } from "@/components/commands/reference";
import type { CommandCategory } from "@/lib/bot/schemas";

const category = (name: string, names: string[]): CommandCategory => ({
  name,
  blurb: `${name} things`,
  emoji: null,
  commands: names.map((n) => ({
    name: n,
    shown_name: `/${n}`,
    description: `Does ${n}`,
    details: `Does ${n} at length`,
    usage: `/${n}`,
    example: `/${n}`,
    permissions: [],
    guild_only: false,
    cooldown: null,
    slash: true,
    slash_id: null,
  })),
});

describe("filterIndex", () => {
  const categories = [category("Brainrot", ["brainrot pardon", "brainrot score"]), category("General", ["whois", "serverinfo"])];

  it("returns everything for an empty query", () => {
    expect(filterIndex(categories, "  ")).toBe(categories);
  });

  it("matches on name, description, and category, dropping empty categories", () => {
    expect(filterIndex(categories, "pardon").map((c) => c.commands.map((x) => x.name))).toEqual([["brainrot pardon"]]);
    expect(filterIndex(categories, "general").map((c) => c.name)).toEqual(["General"]);
    expect(filterIndex(categories, "brainrot score")).toHaveLength(1);
    expect(filterIndex(categories, "zzz")).toEqual([]);
  });
});
