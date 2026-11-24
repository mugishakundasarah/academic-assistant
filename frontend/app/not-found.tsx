import NextLink from "next/link";

export default function NotFound() {
  return (
    <main className="page">
      <h1>Not found</h1>
      <p>This page or course does not exist. It may not have been synced yet.</p>
      <p>
        <NextLink href="/">Back to the dashboard</NextLink>
      </p>
    </main>
  );
}
