export const dynamic = "force-dynamic";

async function checkBackend(): Promise<boolean> {
  const baseUrl = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
  try {
    const healthUrl = new URL("health", baseUrl.replace(/\/?$/, "/"));
    const response = await fetch(healthUrl, {
      cache: "no-store",
      signal: AbortSignal.timeout(2000),
    });
    if (!response.ok) return false;

    const body = await response.json();
    return body?.status === "ok";
  } catch {
    return false;
  }
}

export default async function HomePage() {
  const connected = await checkBackend();

  return (
    <main>
      <h1>Academic Assistant</h1>
      <p data-connected={connected}>
        {connected ? "Backend connected" : "Backend unavailable"}
      </p>
    </main>
  );
}
