"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { MODULES, moduleHref, type ModuleDefinition } from "@/modules/registry";

/**
 * The module navigation, driven by the registry. A vertical sidebar from lg up; on phones it becomes
 * two rows of scrollable tabs (modules, then the open module's pages) so nothing hides in a drawer.
 */
export function Sidebar({ guildId, modules = MODULES }: { guildId: string; modules?: readonly ModuleDefinition[] }) {
  const pathname = usePathname();
  const active = modules.find((module) => pathname.startsWith(moduleHref(guildId, module))) ?? modules[0];

  const isCurrent = (href: string, exact: boolean) => (exact ? pathname === href : pathname === href || pathname.startsWith(`${href}/`));

  return (
    <>
      <nav aria-label="Modules" className="hidden w-56 shrink-0 flex-col gap-6 lg:flex">
        {modules.map((module) => {
          const base = moduleHref(guildId, module);
          return (
            <div key={module.id}>
              <Link
                href={base}
                aria-current={pathname === base ? "page" : undefined}
                className={`display block px-3 py-1 text-sm font-semibold ${pathname.startsWith(base) ? module.tone.text : "text-fg-muted hover:text-fg"}`}
              >
                {module.label}
              </Link>
              {module.links.length > 1 ? (
                <ul className="mt-1 flex flex-col">
                  {module.links.map((link) => {
                    const href = moduleHref(guildId, module, link);
                    const current = isCurrent(href, link.path === "");
                    return (
                      <li key={href}>
                        <Link
                          href={href}
                          aria-current={current ? "page" : undefined}
                          className={`block border-l-2 py-1.5 pl-3 text-sm ${current ? `${module.tone.border} text-fg` : "border-border text-fg-muted hover:border-border-strong hover:text-fg"}`}
                        >
                          {link.label}
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              ) : null}
            </div>
          );
        })}
      </nav>

      <nav aria-label="Modules" className="-mx-4 flex flex-col border-b border-border lg:hidden">
        <ul className="flex gap-4 overflow-x-auto px-4 [scrollbar-width:none]">
          {modules.map((module) => {
            const href = moduleHref(guildId, module);
            const current = active.id === module.id;
            return (
              <li key={module.id} className="shrink-0">
                <Link
                  href={href}
                  aria-current={current ? "true" : undefined}
                  className={`display -mb-px inline-flex h-10 items-center border-b-2 text-sm font-semibold ${current ? `${module.tone.border} ${module.tone.text}` : "border-transparent text-fg-muted"}`}
                >
                  {module.label}
                </Link>
              </li>
            );
          })}
        </ul>
        {active.links.length > 1 ? (
          <ul className="flex gap-1 overflow-x-auto border-t border-border px-4 py-2 [scrollbar-width:none]">
            {active.links.map((link) => {
              const href = moduleHref(guildId, active, link);
              const current = isCurrent(href, link.path === "");
              return (
                <li key={href} className="shrink-0">
                  <Link
                    href={href}
                    aria-current={current ? "page" : undefined}
                    className={`inline-flex h-8 items-center rounded-[var(--radius-control)] px-2.5 text-sm ${current ? "bg-surface-3 text-fg" : "text-fg-muted"}`}
                  >
                    {link.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        ) : null}
      </nav>
    </>
  );
}
