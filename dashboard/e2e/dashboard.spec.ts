import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { GUILD, sessionCookie } from "./session";

const BRAINROT = `/g/${GUILD}/brainrot`;

async function signIn(page: Page) {
  const value = await sessionCookie();
  await page.context().addCookies([{ name: "sprok_session", value, domain: "127.0.0.1", path: "/" }]);
}

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "no horizontal scroll").toBeLessThanOrEqual(0);
}

async function accessible(page: Page) {
  await expect(page).toHaveTitle(/Sprok/); // streamed metadata lands a beat after a client-side navigation
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
}

test.beforeEach(async ({ page }) => {
  page.on("console", (message) => {
    // a 404 page is itself a "failed to load resource"; everything else (csp, hydration, react) fails the test
    if (message.type() === "error" && !/Failed to load resource.*404/.test(message.text())) {
      throw new Error(`console error: ${message.text()}`);
    }
  });
});

test("public pages render, search filters, and copy works", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-write", "clipboard-read"]);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Manage Sprok");
  await noHorizontalScroll(page);
  await accessible(page);

  await page.goto("/commands");
  await expect(page.getByRole("heading", { level: 1, name: "Commands" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 3, name: "/brainrot pardon" })).toBeVisible();
  await page.getByLabel("Search commands").fill("whois");
  await expect(page.getByRole("heading", { level: 3, name: "/whois" })).toBeVisible();
  await expect(page.getByRole("heading", { level: 3, name: "/brainrot pardon" })).toHaveCount(0);
  await page.getByLabel("Search commands").fill("");
  await page.getByRole("button", { name: "Copy usage" }).first().click();
  await expect(page.getByText("Copied").first()).toBeVisible();
  await noHorizontalScroll(page);
  await accessible(page);

  await page.goto("/privacy");
  await expect(page.getByRole("heading", { level: 1, name: "Privacy policy" })).toBeVisible();
  await accessible(page);
});

test("signed out, the dashboard redirects home with a reason", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/\?next=%2Fdashboard/);
});

test("picker, shell, and every anti-brainrot screen", async ({ page }) => {
  await signIn(page);
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { level: 1, name: "Your servers" })).toBeVisible();
  await page.getByRole("link", { name: /The Kitchen/ }).click();
  await expect(page).toHaveURL(new RegExp(`/g/${GUILD}/commands`));
  await expect(page.getByRole("navigation", { name: "Modules" }).first()).toBeVisible();
  await noHorizontalScroll(page);
  await accessible(page);

  // overview: turn off (with confirmation), then back on
  await page.goto(BRAINROT);
  const toggle = page.getByRole("switch", { name: "Anti-brainrot" });
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await toggle.click();
  await page.getByRole("button", { name: "Turn off" }).click();
  await expect(toggle).toHaveAttribute("aria-checked", "false");
  await expect(page.getByRole("status").filter({ hasText: "Anti-brainrot is off" })).toBeVisible();
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "true");
  await noHorizontalScroll(page);
  await accessible(page);

  // channels: flip voice-chat, save, see it persist (the stub keeps state between projects, so flip, not set)
  await page.goto(`${BRAINROT}/channels`);
  await page.getByLabel("Find a channel").fill("voice");
  const voice = page.getByRole("checkbox", { name: /voice-chat/ });
  const wasWatched = await voice.isChecked();
  await voice.click();
  await page.getByRole("button", { name: "Save channels" }).click();
  await expect(page.getByRole("status").filter({ hasText: /Watching \d+ channel/ })).toBeVisible();
  await page.reload();
  await page.getByLabel("Find a channel").fill("voice");
  await expect(page.getByRole("checkbox", { name: /voice-chat/ })).toBeChecked({ checked: !wasWatched });
  await noHorizontalScroll(page);
  await accessible(page);

  // terms: a default off, a custom one on, save; the allowlist separately; a too-short term is refused locally
  await page.goto(`${BRAINROT}/terms`);
  await expect(page.getByRole("checkbox", { name: "sigma allowed" })).toBeDisabled();
  await page.getByRole("checkbox", { name: "rizz", exact: true }).click();
  const custom = page.getByRole("textbox", { name: "Custom terms" });
  const term = `sybau${test.info().project.name}`;
  await custom.fill(term);
  await custom.press("Enter");
  await page.getByRole("button", { name: "Save vocabulary" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Vocabulary saved" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Custom terms list" })).toContainText(term);
  await custom.fill("no");
  await custom.press("Enter");
  await expect(page.getByRole("alert").filter({ hasText: "too short" })).toBeVisible();
  const allow = page.getByRole("textbox", { name: "Allowlist" });
  await allow.fill(`gyat${test.info().project.name}`);
  await allow.press("Enter");
  await page.getByRole("button", { name: "Save allowlist" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Allowlist saved" })).toBeVisible();
  await noHorizontalScroll(page);
  await accessible(page);

  // exemptions: a role by checkbox, a member by search, save
  await page.goto(`${BRAINROT}/exemptions`);
  await page.getByRole("checkbox", { name: /mods/ }).click();
  const who = test.info().project.name === "phone" ? "user" : "mod";
  await page.getByLabel("Add a member").fill(who);
  await page.getByRole("option", { name: new RegExp(who) }).first().click();
  await page.getByRole("button", { name: "Save exemptions" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Exemptions saved" })).toBeVisible();
  await noHorizontalScroll(page);
  await accessible(page);

  // settings: friendly durations in, a bad one refused before it leaves, then a save
  await page.goto(`${BRAINROT}/settings`);
  await page.getByLabel("Mute duration").fill("abc");
  await expect(page.getByText("Whole minutes", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Save settings" })).toBeDisabled();
  const mute = test.info().project.name === "phone" ? "15m" : "10m";
  await page.getByLabel("Mute duration").fill(mute);
  await page.getByLabel("Repeat ladder").fill("1h 6h 1d");
  await page.getByLabel("Warnings stay for").fill("0");
  await page.getByLabel("Mute mode").selectOption("role");
  await page.getByLabel("Muted role").selectOption({ label: "muted" });
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Settings saved" })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Mute duration")).toHaveValue(mute);
  await expect(page.getByLabel("Repeat ladder")).toHaveValue("1h 6h 1d");
  await noHorizontalScroll(page);
  await accessible(page);

  // offenders: pardon with confirmation, then the leaderboard tab
  await page.goto(`${BRAINROT}/offenders`);
  await page.getByRole("button", { name: "Pardon" }).first().click();
  await page.getByRole("button", { name: /^Pardon .+/ }).click();
  await expect(page.getByRole("status").filter({ hasText: "Pardoned" })).toBeVisible();
  await page.getByRole("link", { name: "Leaderboard" }).click();
  await expect(page).toHaveURL(/sort=lifetime/);
  await expect(page.getByText(/Cooked/).locator("visible=true").first()).toBeVisible();
  await noHorizontalScroll(page);
  await accessible(page);

  // activity: the dashboard changes above are in the feed, and the filter narrows it
  await page.goto(`${BRAINROT}/activity`);
  await expect(page.getByText("Mute duration", { exact: false }).first()).toBeVisible();
  await page.getByLabel("Source").selectOption("dashboard");
  await page.getByRole("button", { name: "Filter" }).click();
  await expect(page).toHaveURL(/source=dashboard/);
  const rows = page.locator("main li");
  await expect(rows.filter({ hasText: "dashboard" }).first()).toBeVisible();
  await expect(rows.filter({ hasText: /Warning|Spam|Mute|Timeout/ }).filter({ hasText: "auto" })).toHaveCount(0);
  await noHorizontalScroll(page);
  await accessible(page);

  // the server switcher keeps the module when switching (only one server in the stub, so: back to all)
  await page.getByRole("combobox", { name: "Server" }).selectOption("__all__");
  await expect(page).toHaveURL(/\/dashboard$/);
});

test("a server the bot doesn't know is a 404", async ({ page }) => {
  await signIn(page);
  const response = await page.goto("/g/100000000000000999/commands");
  expect(response?.status()).toBe(404);
  await expect(page.getByRole("heading", { level: 1, name: "Nothing here" })).toBeVisible();
});
