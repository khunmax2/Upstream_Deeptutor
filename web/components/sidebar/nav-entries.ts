import {
  BookOpen,
  BookText,
  Bot,
  Brain,
  HeartHandshake,
  House,
  LayoutGrid,
  Library,
  PawPrint,
  PenLine,
  Route,
  Settings,
  type LucideIcon,
} from "lucide-react";

import type { Capability } from "@/lib/capability-routes";

export interface NavEntry {
  href: string;
  label: string;
  icon: LucideIcon;
  tooltipKey?: string;
  /** Model capability this feature needs; locked when the user lacks it. */
  requires?: Capability;
  /**
   * Learning surface this feature's APIs sit behind, mirroring
   * `_learning_surface_for_path` in `deeptutor/api/routers/auth.py`.
   *
   * A learning account is default-deny: `require_learning_surface` answers 403
   * for anything outside its `allowed_surfaces`. Entries left undeclared are
   * treated as restricted, so a new feature is hidden from restricted learners
   * until someone decides which surface it belongs to — the safe direction.
   * `undefined` on an *unrestricted* account changes nothing.
   *
   * `"unrestricted"` marks an entry whose APIs are *not* behind that guard —
   * Settings is the case that matters: `/api/settings/ui` answers 200 for a
   * restricted learner, and hiding it would strand them with no way to change
   * their own language or theme. Verified against the running server rather
   * than assumed, because the guard is applied router by router in
   * `api/main.py` and the list is not obvious from the route path alone.
   */
  surface?: "chat" | "reading" | "unrestricted";
}

/**
 * The workspace features, in the order they ship in.
 *
 * This is the *default* arrangement, not the rendered one — a learner can
 * reorder these and fold the ones they don't use into "More"
 * (``lib/sidebar-layout.ts``). Adding an entry here places it for everyone,
 * including people who have already arranged their sidebar: it arrives next to
 * the neighbour it follows below rather than at the bottom of their list.
 */
export const PRIMARY_NAV: NavEntry[] = [
  {
    href: "/chat",
    surface: "chat",
    label: "Home",
    icon: House,
    tooltipKey: "Home tooltip",
    requires: "llm",
  },
  {
    href: "/partners",
    label: "Partners",
    icon: HeartHandshake,
    tooltipKey: "Partners tooltip",
    requires: "llm",
  },
  {
    // My Agents is its own top-level feature (pulled out of the Learning
    // Space): connect a live local Claude Code / Codex to consult in chat,
    // and manage imported agent conversations. Ungated — managing connections
    // and imports needs no per-user model grant.
    href: "/agents",
    label: "My Agents",
    icon: Bot,
    tooltipKey: "Agents tooltip",
  },
  {
    href: "/co-writer",
    label: "Co-Writer",
    icon: PenLine,
    tooltipKey: "Co-Writer tooltip",
    requires: "llm",
  },
  {
    href: "/books",
    // "Book nav", not the generic "Book" key: the sidebar label says what you
    // do here (compile your own material into a book), while "Book" stays the
    // short type badge used on context chips (Book · 3 chapters).
    label: "Book nav",
    icon: Library,
    tooltipKey: "Book tooltip",
    requires: "llm",
  },
  // Courses nav entry temporarily hidden pending further product work.
  // The route and its data are untouched — only this entry point is gone.
  {
    href: "/mastery",
    label: "Mastery Path",
    icon: Route,
    tooltipKey: "Learn through a living mastery map",
    requires: "llm",
  },
  {
    href: "/reading",
    surface: "reading",
    label: "Immersive Reading",
    icon: BookText,
    tooltipKey: "Immersive Reading tooltip",
    requires: "llm",
  },
  {
    // Learner Anima: the learning-companion pet, pulled out to top level so it
    // is one click from anywhere. One pet per user, fed by every mastery path.
    // Ungated — it only reads learning state, no per-user model grant needed.
    href: "/anima",
    label: "Learner Anima",
    icon: PawPrint,
    tooltipKey: "Anima tooltip",
  },
  {
    href: "/space",
    label: "Learning Space",
    icon: LayoutGrid,
    tooltipKey: "Space tooltip",
  },
];

/** Consoles that sit under the chat history. Not arrangeable: Settings has to
 *  stay findable, and a console nobody folds away is one less thing to explain. */
export const SECONDARY_NAV: NavEntry[] = [
  {
    // Memory is its own top-level console (pulled out of the Learning Space):
    // a place to inspect and curate the tutor's long-term memory, not a daily
    // workspace. Never gated — memory has no per-user model requirement.
    href: "/memory",
    label: "Memory",
    icon: Brain,
    tooltipKey: "Memory tooltip",
  },
  {
    // Knowledge Center sits just above Settings: it's a console for managing
    // KBs and retrieval engines, not a daily workspace. Never gated — embedding
    // / search are shared admin infrastructure, no per-user model grant needed.
    href: "/knowledge-bases",
    label: "Knowledge Center",
    icon: BookOpen,
    tooltipKey: "Knowledge tooltip",
  },
  {
    href: "/settings",
    label: "Settings",
    icon: Settings,
    surface: "unrestricted",
  },
];

export const PRIMARY_NAV_HREFS = PRIMARY_NAV.map((entry) => entry.href);

export const NAV_BY_HREF = new Map(
  [...PRIMARY_NAV, ...SECONDARY_NAV].map((entry) => [entry.href, entry]),
);

export function isNavActive(pathname: string, href: string) {
  if (href === "/space") {
    return (
      (pathname === "/space" || pathname.startsWith("/space/")) &&
      !pathname.startsWith("/mastery")
    );
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * Keep only the entries a learning account can actually reach.
 *
 * `allowedSurfaces` is null for an ordinary account and returns the list
 * untouched. An entry with no declared `surface` is treated as restricted: its
 * router sits behind `require_learning_surface`, which default-denies anything
 * it cannot map, so showing it would just produce a 403 on click.
 */
export function filterNavBySurfaces<
  T extends { href: string; surface?: string },
>(entries: readonly T[], allowedSurfaces: readonly string[] | null): T[] {
  if (!allowedSurfaces) return [...entries];
  const allowed = new Set(allowedSurfaces);
  return entries.filter(
    (entry) =>
      entry.surface === "unrestricted" ||
      (entry.surface !== undefined && allowed.has(entry.surface)),
  );
}
