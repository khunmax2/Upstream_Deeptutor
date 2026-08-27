"use client";

/**
 * Sender allow-list editor for a partner channel (`allow_from`).
 *
 * The generic schema form renders this field as a bare "one value per line"
 * textarea, which hides what the two special values mean and reads backwards:
 *
 *   []      deny everyone — the channel goes silent. Intuition says an empty
 *           list means "no restriction", so this is the classic support case.
 *   ["*"]   allow everyone who can reach the channel, on the owner's API key
 *           and with whatever tools the partner has mounted.
 *
 * Upstream defaults this to `[]` (deny-by-default, see `LineConfig.allow_from`
 * and the "allow_from is empty — all access denied" warning in
 * `channels/base.py`), so `["*"]` is always a deliberate local widening. This
 * control makes the three states explicit and names the consequence of each,
 * while still exposing the raw list for the case that actually needs it.
 */

import { useTranslation } from "react-i18next";

export type AllowFromMode = "list" | "everyone" | "none";

/** Any list containing "*" is "everyone" — `is_allowed` short-circuits on it. */
export function modeOf(value: string[]): AllowFromMode {
  if (value.includes("*")) return "everyone";
  return value.length === 0 ? "none" : "list";
}

/**
 * Value to store for a mode. Switching to "list" keeps whatever concrete
 * senders were already entered, so toggling to "everyone" and back does not
 * silently discard them.
 */
export function valueForMode(mode: AllowFromMode, current: string[]): string[] {
  if (mode === "everyone") return ["*"];
  if (mode === "none") return [];
  return current.filter((entry) => entry !== "*");
}

const OPTIONS: { mode: AllowFromMode; icon: string }[] = [
  { mode: "list", icon: "🔒" },
  { mode: "everyone", icon: "🌐" },
  { mode: "none", icon: "⛔" },
];

export default function AllowFromField({
  value,
  onChange,
}: {
  value: string[];
  onChange: (next: string[]) => void;
}) {
  const { t } = useTranslation();
  const mode = modeOf(value);
  const listed = value.filter((entry) => entry !== "*");

  const labels: Record<AllowFromMode, { title: string; hint: string }> = {
    list: {
      title: t("Only these senders"),
      hint: t("One sender id per line."),
    },
    everyone: {
      title: t("Anyone"),
      hint: t("Every user who can reach this channel."),
    },
    none: {
      title: t("No one"),
      hint: t("The channel accepts nothing — it will look unresponsive."),
    },
  };

  return (
    <div>
      <label className="mb-1.5 block text-[12px] font-medium text-[var(--foreground)]">
        {t("Who may talk to this partner")}
      </label>

      <div className="space-y-1.5">
        {OPTIONS.map(({ mode: option, icon }) => (
          <label
            key={option}
            className={`flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2 transition-colors ${
              mode === option
                ? "border-[var(--ring)] bg-[var(--muted)]"
                : "border-[var(--border)] hover:border-[var(--ring)]"
            }`}
          >
            <input
              type="radio"
              name="allow-from-mode"
              checked={mode === option}
              onChange={() => onChange(valueForMode(option, listed))}
              className="mt-0.5"
            />
            <span className="min-w-0">
              <span className="block text-[13px] text-[var(--foreground)]">
                {icon} {labels[option].title}
              </span>
              <span className="block text-[11px] text-[var(--muted-foreground)]">
                {labels[option].hint}
              </span>
            </span>
          </label>
        ))}
      </div>

      {mode === "everyone" && (
        <p className="mt-2 rounded-lg border border-red-500/40 bg-red-500/5 px-3 py-2 text-[11.5px] leading-relaxed text-red-600 dark:text-red-400">
          {t(
            "Anyone who finds this channel can use it, billed to your API key. They reach the partner's mounted tools and its memory — review the Tools tab before leaving this on.",
          )}
        </p>
      )}

      {mode === "list" && (
        <textarea
          value={listed.join("\n")}
          onChange={(e) =>
            onChange(
              e.target.value
                .split("\n")
                .map((line) => line.trim())
                .filter(Boolean),
            )
          }
          rows={Math.max(3, Math.min(8, listed.length + 1))}
          placeholder={t("One sender id per line")}
          className="mt-2 w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-2 font-mono text-[13px] outline-none focus:border-[var(--ring)]"
        />
      )}

      {mode === "list" && listed.length === 0 && (
        <p className="mt-1.5 text-[11px] text-amber-600 dark:text-amber-400">
          {t("No senders listed yet — the channel will reject every message.")}
        </p>
      )}
    </div>
  );
}
