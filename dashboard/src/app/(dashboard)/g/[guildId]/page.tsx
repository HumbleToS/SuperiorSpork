import { redirect } from "next/navigation";
import { MODULES, moduleHref } from "@/modules/registry";

export default async function GuildIndexPage({ params }: PageProps<"/g/[guildId]">) {
  const { guildId } = await params;
  redirect(moduleHref(guildId, MODULES[0]));
}
