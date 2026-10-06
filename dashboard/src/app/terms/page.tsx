import type { Metadata } from "next";
import { PublicFrame } from "@/components/shell/public-frame";
import { LegalPage } from "@/components/legal";
import { getSession } from "@/lib/auth/session";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Terms of service",
  description: "The terms for using the Sprok Discord bot and its dashboard.",
  alternates: { canonical: "https://terms.sprok.umbleh.dev/" },
};

export default async function TermsPage() {
  const session = await getSession();
  return (
    <PublicFrame signedIn={session !== null}>
      <LegalPage title="Terms of service" updated="2026-09-16">
        <p>
          These terms cover the Sprok Discord bot and the dashboard at sprok.umbleh.dev, operated by umbleh. By adding the bot to a
          server or signing in to the dashboard you agree to them. They sit on top of Discord&rsquo;s own Terms of Service and
          Community Guidelines, which always apply.
        </p>

        <h2>Using the bot</h2>
        <ul>
          <li>You need to be allowed to add bots to a server to add this one, and to have Manage Server to use the dashboard for it.</li>
          <li>
            Don&rsquo;t use the bot to break Discord&rsquo;s rules, to harass anyone, or to record people who haven&rsquo;t agreed to it. Voice
            recording announces itself and only captures members who acknowledged inclusion; don&rsquo;t try to get around that.
          </li>
          <li>Don&rsquo;t try to overload, probe, or reverse the bot, its API, or the dashboard.</li>
          <li>Server admins are responsible for how they configure features in their server, including the anti-brainrot word list.</li>
        </ul>

        <h2>Paid features</h2>
        <p>
          Voice recaps are metered by recorded minutes per month. A free allowance exists; anything beyond it is sold through Discord
          (Premium Apps) under Discord&rsquo;s purchase terms. Prices and allowances may change; changes apply from the next billing
          period.
        </p>

        <h2>Availability</h2>
        <p>
          The bot and dashboard are provided as-is and as-available, with no guarantee of uptime. Features can change or be removed.
          If the bot is unreachable, the dashboard says so and changes nothing.
        </p>

        <h2>Your data</h2>
        <p>
          What is collected and how to delete it is in the <a href="/privacy">privacy policy</a>. Removing the bot from a server deletes
          that server&rsquo;s data.
        </p>

        <h2>Liability</h2>
        <p>
          To the extent the law allows, umbleh is not liable for losses that come from using or being unable to use the bot or the
          dashboard, including anything caused by third-party services the bot depends on.
        </p>

        <h2>Ending things</h2>
        <p>
          You can stop at any time by removing the bot or signing out. The operator may remove the bot from a server, or refuse the
          dashboard to an account, that breaks these terms.
        </p>

        <h2>Changes</h2>
        <p>These terms may change; the date above will move when they do. Continuing to use the bot after a change means accepting it.</p>

        <h2>Contact</h2>
        <p>
          Use the <code>report</code> command in any server with the bot, or the contact details on umbleh.dev.
        </p>
      </LegalPage>
    </PublicFrame>
  );
}
