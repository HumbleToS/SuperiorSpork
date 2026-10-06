import type { Metadata, Viewport } from "next";
import { bricolage, plexMono, plexSans } from "./fonts";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://sprok.umbleh.dev"),
  title: {
    default: "Sprok",
    template: "%s · Sprok",
  },
  description: "The dashboard for the Sprok Discord bot: browse every command and manage your server's settings.",
};

// Every page carries a per-request CSP nonce (src/proxy.ts), so nothing is prerendered.
export const dynamic = "force-dynamic";

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f2eee7" },
    { media: "(prefers-color-scheme: dark)", color: "#1a1816" },
  ],
  colorScheme: "light dark",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${bricolage.variable} ${plexSans.variable} ${plexMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col">
        <a
          href="#main"
          className="sr-only-focusable fixed top-2 left-2 z-50 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-fg"
        >
          Skip to content
        </a>
        {children}
      </body>
    </html>
  );
}
