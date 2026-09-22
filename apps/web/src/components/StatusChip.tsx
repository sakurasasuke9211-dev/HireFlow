import type { MatchStatus } from "@/lib/types";
import { statusMeta, toUiStatus } from "@/lib/screening";

export function StatusChip({
  status,
  children,
}: {
  status: MatchStatus | null | undefined;
  children?: React.ReactNode;
}) {
  if (!status) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-line px-2.5 py-0.5 text-xs font-semibold text-ink-400">
        Not run
      </span>
    );
  }
  const meta = statusMeta[toUiStatus(status)];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${meta.chip}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} aria-hidden="true" />
      {children ?? meta.label}
    </span>
  );
}
