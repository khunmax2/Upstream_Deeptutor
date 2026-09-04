/**
 * The upstream project's own outbound links, and the flag that parks them.
 *
 * This fork ships as **DeepWitya** to learners — including children on
 * `learner` and policy-bound accounts — so the sidebar footer and the Settings
 * ▸ About "Project" section were pointing an audience that has no use for them
 * at someone else's source repository and someone else's documentation site.
 * Both are hidden by default now.
 *
 * Parked, not deleted, and behind the same shape of switch the floating call
 * button uses (`NEXT_PUBLIC_VOICE_CALL`): set `NEXT_PUBLIC_UPSTREAM_LINKS` to
 * `1` or `true` and every one of them comes straight back. Keeping the URLs and
 * the markup in place is what makes this the cheapest thing to resolve on an
 * upstream sync — the diff is a guard, not a removal.
 *
 * **This is not the fork's Apache-2.0 attribution.** That obligation is met by
 * the `NOTICE` and `LICENSE` files and the modification record in `CHANGES.md`,
 * which §4 of the licence asks to travel with the *distribution* — not by a link
 * in a running UI. Hiding these does not touch it, and none of those files may
 * be weakened to match.
 *
 * Consumed by `components/sidebar/SidebarShell.tsx` (both the collapsed and the
 * expanded footer) and `features/settings/sections/AboutSettingsSection.tsx`.
 * It lives here, in a new file, so those two upstream files each carry a guard
 * and an import rather than a copy of this reasoning.
 */

/** Upstream's marketing site — the sidebar footer's book icon. */
export const UPSTREAM_DOCS_URL = "https://deeptutor.info/";

/** Upstream's documentation site — the About panel's "Documentation" row. */
export const UPSTREAM_DOCS_SITE_URL = "https://docs.deeptutor.info";

/** Upstream's source repository. */
export const UPSTREAM_REPO_URL = "https://github.com/HKUDS/DeepTutor";

/**
 * Whether to show the links above. Off unless explicitly switched on, so a
 * build that says nothing about it ships without them.
 */
export const UPSTREAM_LINKS_ENABLED = ["1", "true"].includes(
  (process.env.NEXT_PUBLIC_UPSTREAM_LINKS ?? "").toLowerCase(),
);
