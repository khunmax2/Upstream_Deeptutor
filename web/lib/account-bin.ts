/**
 * Fork (admin design §4, Phase 2): how long a deleted account stays in the
 * bin before the primary admin is shown "retention over". Nothing purges by
 * itself -- the count is advice on the page, the purge is a person's press
 * (decision 10, 2026-09-18).
 */
export const BIN_RETENTION_DAYS = 30;

/** Days left before the bin's retention runs out; 0 once it has. */
export function binDaysLeft(deletedAt: string, now = Date.now()): number {
  const started = Date.parse(deletedAt);
  if (Number.isNaN(started)) return BIN_RETENTION_DAYS;
  const elapsed = (now - started) / 86_400_000;
  return Math.max(0, Math.ceil(BIN_RETENTION_DAYS - elapsed));
}
