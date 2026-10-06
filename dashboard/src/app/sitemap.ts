import type { MetadataRoute } from "next";

export default function sitemap(): MetadataRoute.Sitemap {
  const base = "https://sprok.umbleh.dev";
  return [
    { url: `${base}/`, changeFrequency: "monthly", priority: 0.6 },
    { url: `${base}/commands`, changeFrequency: "weekly", priority: 1 },
    { url: `${base}/privacy`, changeFrequency: "yearly", priority: 0.3 },
    { url: `${base}/terms`, changeFrequency: "yearly", priority: 0.3 },
  ];
}
