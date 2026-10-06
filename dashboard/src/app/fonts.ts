import localFont from "next/font/local";

// Self-hosted fonts (OFL, licenses beside the files). No font CDNs, no Google Fonts requests.
export const bricolage = localFont({
  src: "../assets/fonts/bricolage-grotesque-latin-wght-normal.woff2",
  variable: "--font-bricolage",
  weight: "200 800",
  display: "swap",
});

export const plexSans = localFont({
  src: "../assets/fonts/ibm-plex-sans-latin-wght-normal.woff2",
  variable: "--font-plex-sans",
  weight: "100 700",
  display: "swap",
});

export const plexMono = localFont({
  src: [
    { path: "../assets/fonts/ibm-plex-mono-latin-400-normal.woff2", weight: "400" },
    { path: "../assets/fonts/ibm-plex-mono-latin-500-normal.woff2", weight: "500" },
  ],
  variable: "--font-plex-mono",
  display: "swap",
});
