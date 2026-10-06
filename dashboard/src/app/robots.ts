import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: ["/", "/commands", "/privacy", "/terms"], disallow: ["/dashboard", "/g/", "/api/"] }],
    sitemap: "https://sprok.umbleh.dev/sitemap.xml",
  };
}
