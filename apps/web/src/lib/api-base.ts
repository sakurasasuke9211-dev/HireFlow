/** Local dev uses /backend proxy; production browser calls Render directly (Vercel Hobby ~10s limit). */
export function getApiBase(): string {
  if (typeof window !== "undefined") {
    const direct = process.env.NEXT_PUBLIC_HIREFLOW_API_URL?.trim();
    if (direct) return direct.replace(/\/$/, "");
  }
  return "/backend";
}
