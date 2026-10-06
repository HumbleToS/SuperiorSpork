import type { Metadata } from "next";

/** Everything behind sign-in is private: no indexing, and every page is rendered per request. */
export const metadata: Metadata = { robots: { index: false, follow: false } };
export const dynamic = "force-dynamic";

export default function DashboardGroupLayout({ children }: LayoutProps<"/">) {
  return children;
}
