/**
 * The module registry drives the sidebar. Add a module here and it appears for every server;
 * nothing else needs to change. Order is the sidebar order.
 */
export type ModuleId = "commands" | "brainrot";

export type ModuleLink = {
  /** Sidebar label. */
  label: string;
  /** Path under /g/[guildId]/<module>. Empty string is the module's index page. */
  path: string;
};

/** A module's colour from the syntax palette. Whole class names, so Tailwind sees them. */
export type ModuleTone = { text: string; border: string };

export const TONES = {
  blue: { text: "text-blue", border: "border-blue" },
  orange: { text: "text-orange", border: "border-orange" },
} as const satisfies Record<string, ModuleTone>;

export type ModuleDefinition = {
  id: ModuleId;
  /** Sidebar label. */
  label: string;
  /** The module's colour: its label in the sidebar, the rule under its tab, the eyebrow on its pages. */
  tone: ModuleTone;
  /** One line under the label on the module's index page. */
  blurb: string;
  /** Sub-pages inside the module, in sidebar order. The first one is the index. */
  links: readonly ModuleLink[];
};

export const MODULES: readonly ModuleDefinition[] = [
  {
    id: "commands",
    label: "Commands",
    tone: TONES.blue,
    blurb: "Every command the bot has, straight from its own help.",
    links: [{ label: "Reference", path: "" }],
  },
  {
    id: "brainrot",
    label: "Anti-brainrot",
    tone: TONES.orange,
    blurb: "Heat, mutes, and the leaderboard for brainrot vocabulary.",
    links: [
      { label: "Overview", path: "" },
      { label: "Channels", path: "/channels" },
      { label: "Terms", path: "/terms" },
      { label: "Exemptions", path: "/exemptions" },
      { label: "Settings", path: "/settings" },
      { label: "Offenders", path: "/offenders" },
      { label: "Activity", path: "/activity" },
    ],
  },
] as const;

export function moduleHref(guildId: string, module: ModuleDefinition, link?: ModuleLink): string {
  return `/g/${guildId}/${module.id}${link?.path ?? ""}`;
}

export function findModule(id: string): ModuleDefinition | undefined {
  return MODULES.find((module) => module.id === id);
}
