import type { Metadata } from "next";
import { PublicFrame } from "@/components/shell/public-frame";
import { LegalPage } from "@/components/legal";
import { getSession } from "@/lib/auth/session";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Privacy policy",
  description: "What the Sprok Discord bot and its dashboard collect, why, how long it's kept, and how to delete it.",
  alternates: { canonical: "https://privacy.sprok.umbleh.dev/" },
};

export default async function PrivacyPage() {
  const session = await getSession();
  return (
    <PublicFrame signedIn={session !== null}>
      <LegalPage title="Privacy policy" updated="2026-10-02">
        <p>
          Sprok is a Discord bot and a companion dashboard at sprok.umbleh.dev, operated by umbleh. This policy says what they collect,
          why, how long it&rsquo;s kept, and how to get rid of it. The short version: the bot keeps what it needs to run the features a
          server turns on, never sells or shares it, and deletes it when the server or you say so.
        </p>

        <h2>What the bot collects</h2>
        <h3>Server settings</h3>
        <p>
          Per-server configuration: the command prefix, which features are on, channel and role ids the server picked, and the
          settings for each feature. Stored for as long as the bot is in the server.
        </p>
        <h3>Voice recaps</h3>
        <p>
          Voice audio is captured only during a session someone explicitly starts with <code>record start</code>, announced in the
          channel, and only from members who acknowledged inclusion. Raw audio is deleted the moment transcription finishes. The
          transcript and an AI-written recap are kept for the server&rsquo;s retention window (90 days unless the server changed it)
          and are used only to produce, search, and show recaps in that server. Transcription runs locally; the recap is produced by
          one request to an AI provider that receives the transcript and nothing else about you. A per-server count of recorded
          minutes is kept for quotas. <code>optout</code> permanently excludes your audio in a server.
        </p>
        <h3>Anti-brainrot</h3>
        <p>
          In servers that turn this on, messages in the channels the server opted in are checked against a word list. Only numbers
          are stored: a heat score, counters, timestamps, and an activity log of what the bot did (a warning, a mute, a pardon, a
          settings change) with the ids of who was involved. Message text is never stored, not even in logs.
        </p>
        <h3>Activity counts</h3>
        <p>
          Every server the bot is in gets activity counts: how many messages, joins, leaves, and commands happened per day, by
          channel, by hour, and by member. These are numbers only. The message event is counted; the text is never read or stored,
          and nothing is backfilled from history. Daily counts are kept for 90 days. <code>stats off</code> (Manage Server) stops
          counting and deletes the server&rsquo;s counts at once; <code>stats on</code> starts again from zero.
        </p>

        <h2>What the dashboard collects</h2>
        <p>
          Signing in uses Discord&rsquo;s OAuth2 with two permissions: <strong>identify</strong> (your Discord id, username, and
          avatar) and <strong>guilds</strong> (the list of servers you&rsquo;re in, with your permissions in each). That list is used
          only to show which servers you can manage and which ones could add the bot. It is kept in the dashboard&rsquo;s memory for
          about a minute and is not written to a database. The dashboard has no database of its own.
        </p>
        <h3>The session cookie</h3>
        <p>
          One cookie, <code>sprok_session</code>, holds your Discord id, username, avatar, the access token Discord issued, and its
          expiry. It is encrypted, only sent over HTTPS, not readable by scripts, and expires when the Discord token does (about a
          week). Signing out deletes it. A second, ten-minute cookie exists only while a sign-in is in progress. There are no
          analytics or advertising cookies.
        </p>
        <h3>Actions you take</h3>
        <p>
          When you change a setting or pardon someone from the dashboard, the bot records that you did it (your Discord id, the time,
          and the change) in the same activity log the commands use, and posts a short note to the server&rsquo;s mod log channel if
          one is set. Server admins can see this. It contains no message text.
        </p>

        <h2>Who can see what</h2>
        <p>
          Server admins (members with Manage Server) can see their own server&rsquo;s settings and anti-brainrot data. Recaps are
          visible to the server according to its own settings. Nobody outside the server sees any of it, with the one exception
          below. The operator can access the database for maintenance and does not read or analyse content beyond that.
        </p>
        <h3>Developer access</h3>
        <p>
          The developer has a private set of tools that can show a server&rsquo;s metadata (its name, channels, roles, members and
          their roles, member and online counts) and its activity counts, including one member&rsquo;s counts in one server at a
          time, for support and debugging. They show no message content, pins, or history, and never build a picture of a person
          across servers. Every use is logged. The developer can also delete a member&rsquo;s stored counts on request.
        </p>

        <h2>Third parties</h2>
        <ul>
          <li>
            <strong>Discord</strong> — the platform itself; everything the bot does goes through Discord&rsquo;s API under Discord&rsquo;s
            own policies.
          </li>
          <li>
            <strong>An AI provider</strong> for voice recaps (Anthropic, or Cloudflare Workers AI while testing) — receives a session
            transcript to write the recap, nothing else.
          </li>
          <li>
            <strong>Cloudflare</strong> — sits in front of the dashboard as a proxy and sees the web traffic like any CDN.
          </li>
        </ul>
        <p>Nothing is sold, and nothing is used for advertising or profiling.</p>

        <h2>How long, and how to delete</h2>
        <ul>
          <li>Recaps and transcripts: the server&rsquo;s retention window, or <code>recap delete</code> for one session.</li>
          <li>Anti-brainrot numbers: pruned automatically once they have decayed; the activity log keeps 30 days.</li>
          <li>
            Activity counts: 90 days, or at once with <code>stats off</code> (Manage Server). After the bot is removed from a server
            its counts go seven days later, in case the removal was a mistake. <code>report</code> asks for your own counts to be
            deleted.
          </li>
          <li>Everything else for a server: deleted when the bot is removed from that server.</li>
          <li>Your dashboard session: sign out, or wait for it to expire.</li>
        </ul>
        <p>
          To ask for anything else, use the <code>report</code> command in any server with the bot, or the contact details on
          umbleh.dev.
        </p>

        <h2>Changes</h2>
        <p>If this policy changes in a way that matters, the date above changes with it and the bot&rsquo;s <code>privacy</code> command links here.</p>
      </LegalPage>
    </PublicFrame>
  );
}
