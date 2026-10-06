import Link from "next/link";

export default function NotFound() {
  return (
    <main id="main" className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-4 px-4 text-center">
      <h1 className="text-3xl font-semibold">Nothing here</h1>
      <p className="text-fg-muted">That page doesn&rsquo;t exist, or you don&rsquo;t manage that server.</p>
      <Link href="/dashboard" className="text-accent underline-offset-4 hover:underline">
        Back to your servers
      </Link>
    </main>
  );
}
