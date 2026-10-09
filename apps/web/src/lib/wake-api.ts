import { getApiBase } from "./api-base";

/** Ping API on auth pages so Render free tier can finish cold start before submit. */
export function wakeApi(): void {
  void fetch(`${getApiBase()}/health`, { cache: "no-store" }).catch(() => undefined);
}
