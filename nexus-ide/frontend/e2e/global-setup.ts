import fs from "node:fs";
import path from "node:path";

const AUTH_STATE_PATH = path.resolve("test-results/.auth/user.json");

function readLocalEnvironment(): Record<string, string> {
  const envPath = path.resolve(".env.local");
  const result: Record<string, string> = {};

  for (const rawLine of fs.readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const separator = line.indexOf("=");
    if (separator < 1) continue;
    const key = line.slice(0, separator).trim();
    const value = line.slice(separator + 1).trim().replace(/^(['"])(.*)\1$/, "$2");
    result[key] = value;
  }

  return result;
}

export default async function globalSetup(): Promise<void> {
  const env = readLocalEnvironment();
  const apiBase = (env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
  const email = env.NEXT_PUBLIC_DEV_EMAIL;
  const password = env.NEXT_PUBLIC_DEV_PASSWORD;

  if (!email || !password) {
    throw new Error("E2E authentication requires NEXT_PUBLIC_DEV_EMAIL and NEXT_PUBLIC_DEV_PASSWORD");
  }

  const response = await fetch(`${apiBase}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    throw new Error(`E2E authentication failed with HTTP ${response.status}`);
  }

  const session = await response.json() as {
    access_token: string;
    refresh_token?: string;
    user: unknown;
  };
  const localStorage = [
    { name: "nexus.access_token", value: session.access_token },
    { name: "nexus.user", value: JSON.stringify(session.user) },
  ];
  if (session.refresh_token) {
    localStorage.push({ name: "nexus.refresh_token", value: session.refresh_token });
  }

  fs.mkdirSync(path.dirname(AUTH_STATE_PATH), { recursive: true });
  fs.writeFileSync(AUTH_STATE_PATH, JSON.stringify({
    cookies: [],
    origins: [{ origin: "http://localhost:3000", localStorage }],
  }));
}
