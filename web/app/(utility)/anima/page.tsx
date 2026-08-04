"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import {
  PawPrint,
  MessageSquare,
  Sparkles,
  Target,
  Trophy,
  Flag,
  RotateCw,
  GraduationCap,
  Map,
  PenLine,
  Users,
  HelpCircle,
} from "lucide-react";

import PetHabitat from "@/components/pet/PetHabitat";
import AnimaTour from "@/components/pet/AnimaTour";
import AnimaGuide from "@/components/pet/AnimaGuide";
import { BookIcon } from "@/components/pet/AnimaIcons";
import {
  fetchPetDashboard,
  type PetDashboard,
  type MasteryAxis,
} from "@/lib/pet-api";

/**
 * Learner Anima — the companion's own top-level dashboard.
 *
 * One pet per user, fed by ALL their mastery paths. The server is authoritative:
 * this page polls ONE aggregate endpoint (`/api/v1/pet/dashboard`) and renders it.
 * Every card is a real learning signal — the mastery profile reuses the tutor's
 * own gate, growth reads mastery levels / error records / next-objective, activity
 * is quiz-only, reviews are due-driven. Nothing here invents a metric or economy.
 */

const POLL_MS = 4000;

// Earthy category accents (harmonized with the warm terracotta theme). Memory
// follows the app's primary; the rest are fixed mid-tones that read on both themes.
const AXIS_COLOR: Record<string, string> = {
  memory: "var(--primary)",
  concept: "#5fa892",
  procedure: "#d9a24a",
  design: "#b07a9c",
};

const NAV = {
  learn: "/home",
  book: "/book",
  coWriter: "/co-writer",
  partners: "/partners",
} as const;

export default function AnimaPage() {
  const { t } = useTranslation();
  const router = useRouter();
  const [dash, setDash] = useState<PetDashboard | null>(null);
  const [offline, setOffline] = useState(false);
  // Reference clock for relative times + the greeting, refreshed each poll (kept
  // out of render so the components stay pure — no Date.now() during render).
  const [now, setNow] = useState(0);
  const [seeded, setSeeded] = useState(false); // true after the first good fetch
  const [tourOpen, setTourOpen] = useState(false);
  const [guideOpen, setGuideOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const next = await fetchPetDashboard();
        if (!cancelled) {
          setDash(next);
          setNow(Date.now() / 1000);
          setOffline(false);
          setSeeded(true);
        }
      } catch {
        if (!cancelled) setOffline(true); // keep the last-good view, flag offline
      }
    };
    poll();
    const id = window.setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  // Open the tour on first visit (deferred a frame so it runs after paint, not
  // synchronously in the effect). The header's "Take a tour" button reopens it.
  useEffect(() => {
    if (localStorage.getItem("anima_tour_seen_v1")) return;
    const id = window.requestAnimationFrame(() => setTourOpen(true));
    return () => window.cancelAnimationFrame(id);
  }, []);

  const closeTour = useCallback(() => {
    setTourOpen(false);
    try {
      localStorage.setItem("anima_tour_seen_v1", "1");
    } catch {
      /* ignore storage errors */
    }
  }, []);

  const greeting = useMemo(() => {
    if (now === 0) return t("Good evening, Pixel is waiting for you");
    const hour = new Date(now * 1000).getHours();
    if (hour < 12) return t("Good morning, Pixel is ready to learn with you");
    if (hour < 17) return t("Good afternoon, Pixel is ready to learn with you");
    return t("Good evening, Pixel is waiting for you");
  }, [now, t]);

  const typeLabel = useCallback(
    (type: string) =>
      ({
        memory: t("Memory"),
        concept: t("Concept"),
        procedure: t("Procedure"),
        design: t("Design"),
      })[type] ?? type,
    [t],
  );

  const pet = dash?.pet ?? null;
  const empty = seeded && (dash?.paths.length ?? 0) === 0;

  return (
    <div className="h-full overflow-y-auto [scrollbar-gutter:stable]">
      <div className="mx-auto max-w-[1180px] px-4 py-6 sm:px-6 sm:py-8">
        {/* header */}
        <header className="mb-5 flex items-start justify-between gap-3 px-1">
          <div>
            <div className="mb-1 flex items-center gap-2 text-[var(--muted-foreground)]">
              <PawPrint className="h-4 w-4" />
              <span className="text-xs font-semibold tracking-wide">
                {t("Learner Anima")}
              </span>
            </div>
            <h1 className="text-lg font-semibold tracking-tight text-[var(--foreground)] sm:text-xl">
              {greeting}
            </h1>
            <p className="mt-0.5 text-sm text-[var(--muted-foreground)]">
              {t("Great learning today! Pixel is ready to grow alongside you.")}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={() => setGuideOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--card)] px-2.5 py-1.5 text-xs font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--primary)] hover:text-[var(--primary)]"
            >
              <HelpCircle className="h-3.5 w-3.5" />
              {t("How it works")}
            </button>
            <button
              type="button"
              onClick={() => setTourOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--card)] px-2.5 py-1.5 text-xs font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--primary)] hover:text-[var(--primary)]"
            >
              <Sparkles className="h-3.5 w-3.5" />
              {t("Take a tour")}
            </button>
          </div>
        </header>

        {/* hero: habitat (left) + status & mastery (right) */}
        <section className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(300px,0.9fr)]">
          <HabitatCard
            pet={pet}
            offline={offline}
            onLearn={() => router.push(NAV.learn)}
            t={t}
          />
          <div className="flex flex-col gap-4">
            <StatusCard
              pet={pet}
              t={t}
              onDetails={() => router.push(NAV.learn)}
            />
            <MasteryCard dash={dash} typeLabel={typeLabel} t={t} />
          </div>
          {/* on lg, the right column stretches to the habitat's height and its two
              cards share it via flex-1 (see StatusCard / MasteryCard) */}
        </section>

        {empty && (
          <div className="mt-4 rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
            <p className="text-sm text-[var(--foreground)]">
              {t(
                "It has nothing to eat yet. Start a Mastery Path and truly master an objective to feed it.",
              )}
            </p>
            <button
              onClick={() => router.push(NAV.learn)}
              className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
            >
              <MessageSquare className="h-3.5 w-3.5" />
              {t("Start in Chat")}
            </button>
          </div>
        )}

        {!empty && (
          <>
            {/* learner growth band */}
            <section
              data-tour="anima-growth"
              className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3"
            >
              <AlmostCard dash={dash} typeLabel={typeLabel} t={t} />
              <WeakPointsCard dash={dash} t={t} />
              <NextStepCard
                dash={dash}
                typeLabel={typeLabel}
                t={t}
                onGo={() => router.push(NAV.learn)}
              />
            </section>

            {/* activity + reviews */}
            <section
              data-tour="anima-activity"
              className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2"
            >
              <QuizLogCard dash={dash} t={t} now={now} />
              <ReviewsCard
                dash={dash}
                typeLabel={typeLabel}
                t={t}
                now={now}
                onReview={() => router.push(NAV.learn)}
              />
            </section>

            {/* paths + shortcuts */}
            <section
              data-tour="anima-paths"
              className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,1.4fr)_minmax(0,0.9fr)]"
            >
              <PathsCard
                dash={dash}
                t={t}
                onManage={() => router.push(NAV.learn)}
              />
              <ShortcutsCard t={t} router={router} />
            </section>
          </>
        )}
      </div>

      {tourOpen && <AnimaTour onClose={closeTour} />}
      {guideOpen && <AnimaGuide onClose={() => setGuideOpen(false)} />}
    </div>
  );
}

type Tr = (k: string, opts?: Record<string, unknown>) => string;

// --- shared bits ------------------------------------------------------------
function Card({
  children,
  className = "",
  dataTour,
}: {
  children: ReactNode;
  className?: string;
  dataTour?: string;
}) {
  return (
    <div
      data-tour={dataTour}
      className={`anima-surface rounded-xl border border-[var(--border)] bg-[var(--card)] ${className}`}
    >
      {children}
    </div>
  );
}

function CardHead({
  title,
  action,
  right,
  icon,
}: {
  title: string;
  action?: { label: string; onClick: () => void };
  right?: ReactNode;
  icon?: { node: ReactNode; color: string };
}) {
  return (
    <div className="flex items-center justify-between gap-2 px-4 pb-2 pt-3.5">
      <div className="flex min-w-0 items-center gap-2.5">
        {icon && (
          <span
            className="grid h-8 w-8 shrink-0 place-items-center rounded-full"
            style={{
              background: `color-mix(in srgb, ${icon.color} 16%, transparent)`,
              color: icon.color,
            }}
          >
            {icon.node}
          </span>
        )}
        <h2 className="truncate text-sm font-semibold text-[var(--foreground)]">
          {title}
        </h2>
      </div>
      {action && (
        <button
          onClick={action.onClick}
          className="text-xs text-[var(--muted-foreground)] transition-colors hover:text-[var(--primary)]"
        >
          {action.label} ›
        </button>
      )}
      {right}
    </div>
  );
}

function Pill({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-full border border-[color-mix(in_srgb,var(--primary)_45%,var(--border))] bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] px-2 py-0.5 text-xs font-semibold text-[var(--primary)]">
      {children}
    </span>
  );
}

function GateMeter({
  pct,
  gate,
  color,
  scale,
}: {
  pct: number;
  gate: number;
  color: string;
  scale: string;
}) {
  return (
    <div>
      <div className="relative mt-2 h-[7px] rounded-full bg-[color-mix(in_srgb,var(--foreground)_9%,transparent)]">
        <div
          className="h-full rounded-full transition-[width] duration-500"
          style={{
            width: `${Math.max(0, Math.min(100, pct))}%`,
            background: color,
          }}
        />
        <span
          className="absolute -top-[3px] h-[13px] w-[2px] rounded-[2px] bg-[var(--foreground)] opacity-50"
          style={{ left: `${Math.max(0, Math.min(100, gate))}%` }}
        />
      </div>
      <div className="mt-1.5 text-[9px] tabular-nums text-[var(--muted-foreground)]">
        {scale}
      </div>
    </div>
  );
}

// --- hero: habitat ----------------------------------------------------------
function HabitatCard({
  pet,
  offline,
  onLearn,
  t,
}: {
  pet: PetDashboard["pet"] | null;
  offline: boolean;
  onLearn: () => void;
  t: Tr;
}) {
  return (
    <Card className="overflow-hidden" dataTour="anima-habitat">
      <div className="flex items-center justify-between px-4 pb-2.5 pt-3.5">
        <div>
          <div className="flex items-center gap-2">
            <strong className="text-lg tracking-tight text-[var(--foreground)]">
              {pet?.name ?? "Pixel"}
            </strong>
            <Pill>
              {t("Lv.")} {pet?.level ?? 1}
            </Pill>
          </div>
          <div className="mt-0.5 text-[11px] uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("Wind Anima")}
          </div>
        </div>
        <span
          className="rounded-full px-2 py-0.5 text-xs font-semibold"
          style={{ color: pet?.sick ? "var(--destructive)" : "var(--primary)" }}
        >
          {pet?.sick ? t("Sick") : t("Healthy")}
        </span>
      </div>

      <div className="relative mx-3.5 overflow-hidden rounded-[10px] border border-[var(--border)]">
        <div className="aspect-[20/13] w-full">
          <PetHabitat controlledState={pet} offline={offline} />
        </div>
      </div>

      <div className="m-3.5 flex items-center gap-3 rounded-[9px] border border-[var(--border)] bg-[color-mix(in_srgb,var(--card)_82%,transparent)] p-2.5">
        <span className="text-xl">🍲</span>
        <div className="min-w-0 flex-1">
          <strong className="block text-xs text-[var(--foreground)]">
            {t("Pixel eats only when you clear a real mastery gate")}
          </strong>
          <span className="mt-0.5 block text-[10px] text-[var(--muted-foreground)]">
            {t(
              "No shortcut feeding — go learn and watch Pixel run to the bowl",
            )}
          </span>
        </div>
        <button
          onClick={onLearn}
          className="inline-flex shrink-0 items-center gap-1 rounded-md bg-[var(--primary)] px-3 py-2 text-[11px] font-semibold text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
        >
          {t("Go learn")} ↗
        </button>
      </div>
    </Card>
  );
}

// --- hero: status -----------------------------------------------------------
function StatusMeter({
  label,
  pct,
  text,
  color,
}: {
  label: string;
  pct: number;
  text: string;
  color: string;
}) {
  return (
    <div className="mt-3.5">
      <div className="mb-1.5 flex items-center justify-between text-xs text-[var(--foreground)]">
        <span>{label}</span>
        <b className="tabular-nums">{text}</b>
      </div>
      <div className="h-[7px] overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--foreground)_9%,transparent)]">
        <div
          className="h-full rounded-full transition-[width] duration-500"
          style={{
            width: `${Math.max(0, Math.min(100, pct))}%`,
            background: color,
          }}
        />
      </div>
    </div>
  );
}

function StatusCard({
  pet,
  t,
  onDetails,
}: {
  pet: PetDashboard["pet"] | null;
  t: Tr;
  onDetails: () => void;
}) {
  const hunger = Math.round(pet?.hunger ?? 0);
  const happy = Math.round(pet?.happy ?? 0);
  const exp = Math.round(pet?.exp ?? 0);
  const expToNext = pet?.expToNext ?? 100;
  const hungerColor =
    hunger >= 75
      ? "var(--destructive)"
      : hunger >= 55
        ? "#d9a24a"
        : "var(--primary)";
  const quote = pet?.sick
    ? t("I don't feel well, but one correct answer can help me.")
    : hunger >= 65
      ? t("I'm hungry... teach me something new, please.")
      : t("Just a little more — let's learn something new!");

  return (
    <Card className="flex flex-1 flex-col" dataTour="anima-status">
      <CardHead title={t("Companion status")} />
      <div className="flex flex-1 flex-col justify-between px-4 pb-4">
        <StatusMeter
          label={t("Hunger")}
          pct={hunger}
          text={`${hunger}%`}
          color={hungerColor}
        />
        <StatusMeter
          label={t("Happiness")}
          pct={happy}
          text={`${happy}%`}
          color="var(--primary)"
        />
        <StatusMeter
          label={t("Knowledge")}
          pct={(exp / expToNext) * 100}
          text={`${exp} / ${expToNext}`}
          color="#5fa892"
        />
        <p className="mt-4 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-3 text-center text-xs leading-relaxed text-[var(--muted-foreground)]">
          “{quote}”
        </p>
        <div className="mt-3 flex justify-center">
          <button
            onClick={onDetails}
            className="rounded-md border border-[color-mix(in_srgb,var(--primary)_35%,var(--border))] bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] px-3 py-1.5 text-xs font-semibold text-[var(--primary)] transition-opacity hover:opacity-90"
          >
            {t("View details")}
          </button>
        </div>
      </div>
    </Card>
  );
}

// --- hero: knowledge mastery profile (bars) ---------------------------------
function MasteryBar({ axis, label }: { axis: MasteryAxis; label: string }) {
  const na = axis.total === 0;
  const pct = na ? 0 : Math.round((axis.mastered / axis.total) * 100);
  return (
    <div className="grid grid-cols-[82px_minmax(0,1fr)_auto] items-center gap-3">
      <span className="text-xs font-semibold text-[var(--foreground)]">
        {label}
      </span>
      <div className="h-2.5 overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--foreground)_9%,transparent)]">
        <div
          className="h-full rounded-full transition-[width] duration-500"
          style={{
            width: `${pct}%`,
            background: AXIS_COLOR[axis.type] ?? "var(--primary)",
          }}
        />
      </div>
      <span className="whitespace-nowrap text-[11px] tabular-nums text-[var(--muted-foreground)]">
        {na ? (
          "N/A"
        ) : (
          <>
            <b className="text-[var(--foreground)]">{pct}%</b> · {axis.mastered}{" "}
            / {axis.total}
          </>
        )}
      </span>
    </div>
  );
}

function MasteryCard({
  dash,
  typeLabel,
  t,
}: {
  dash: PetDashboard | null;
  typeLabel: (type: string) => string;
  t: Tr;
}) {
  return (
    <Card className="flex flex-1 flex-col" dataTour="anima-profile">
      <CardHead title={t("Knowledge Mastery Profile")} />
      <div className="flex flex-1 flex-col justify-between gap-3.5 px-4 pb-4 pt-1.5">
        {(dash?.profile ?? []).map((axis) => (
          <MasteryBar
            key={axis.type}
            axis={axis}
            label={typeLabel(axis.type)}
          />
        ))}
        <p className="mt-1 text-center text-[10px] leading-relaxed text-[var(--muted-foreground)]">
          <b className="text-[var(--foreground)]">
            {dash?.profileMastered ?? 0} / {dash?.profileTotal ?? 0}{" "}
            {t("mastered")}
          </b>{" "}
          · {t("Counted with the tutor's own policy")}
        </p>
      </div>
    </Card>
  );
}

// --- growth: almost there ---------------------------------------------------
function AlmostCard({
  dash,
  typeLabel,
  t,
}: {
  dash: PetDashboard | null;
  typeLabel: (type: string) => string;
  t: Tr;
}) {
  const items = dash?.growth.almost ?? [];
  return (
    <Card>
      <CardHead
        title={t("Close to mastery")}
        icon={{ node: <Target className="h-4 w-4" />, color: "#5fa892" }}
        right={<Pill>{items.length}</Pill>}
      />
      <div className="flex flex-col gap-3.5 px-4 pb-4">
        {items.length === 0 && (
          <p className="py-2 text-center text-[11px] text-[var(--muted-foreground)]">
            —
          </p>
        )}
        {items.map((a) => (
          <div key={`${a.pathName}:${a.knowledgePointId}`}>
            <div className="flex items-baseline justify-between gap-2">
              <strong className="truncate text-xs text-[var(--foreground)]">
                {a.name}
              </strong>
              <span className="whitespace-nowrap text-[10px] font-semibold text-[var(--primary)]">
                {t("{{n}} more correct", { n: a.attemptsNeeded })}
              </span>
            </div>
            <div className="mt-0.5 text-[10px] text-[var(--muted-foreground)]">
              {typeLabel(a.knowledgeType)} · {a.pathName}
            </div>
            <GateMeter
              pct={a.mastery * 100}
              gate={a.gate * 100}
              color="var(--primary)"
              scale={`${Math.round(a.mastery * 100)}% · ${t("gate")} ${Math.round(a.gate * 100)}%`}
            />
          </div>
        ))}
      </div>
    </Card>
  );
}

// --- growth: weak points cleared --------------------------------------------
function WeakPointsCard({ dash, t }: { dash: PetDashboard | null; t: Tr }) {
  const cleared = dash?.growth.weakPointsCleared ?? 0;
  const active = dash?.growth.weakPointsActive ?? 0;
  return (
    <Card>
      <CardHead
        title={t("Weak points cleared")}
        icon={{ node: <Trophy className="h-4 w-4" />, color: "#d9a24a" }}
      />
      <div className="px-4 pb-5 pt-2 text-center">
        <div className="flex items-baseline justify-center gap-1.5">
          <span className="text-[46px] font-extrabold leading-none tracking-tight text-[var(--primary)] tabular-nums">
            {cleared}
          </span>
        </div>
        <p className="mt-2.5 text-[11px] text-[var(--muted-foreground)]">
          {t("misconceptions you worked through")}
        </p>
        {active > 0 && (
          <div className="mt-3.5 inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] px-3 py-1.5 text-[10px] text-[var(--muted-foreground)]">
            <span className="h-1.5 w-1.5 rounded-full bg-[#d9a24a]" />
            {t("{{n}} still in progress", { n: active })}
          </div>
        )}
      </div>
    </Card>
  );
}

// --- growth: next step ------------------------------------------------------
const ACTION_KEY: Record<string, string> = {
  practice: "Practice",
  assess: "Explain it",
  review: "Review",
  probe: "Try it",
  complete: "Complete",
  answer_pending: "Continue",
};

function NextStepCard({
  dash,
  typeLabel,
  t,
  onGo,
}: {
  dash: PetDashboard | null;
  typeLabel: (type: string) => string;
  t: Tr;
  onGo: () => void;
}) {
  const ns = dash?.growth.nextStep ?? null;
  return (
    <Card>
      <CardHead
        title={t("Next step")}
        icon={{ node: <Flag className="h-4 w-4" />, color: "#b07a9c" }}
        right={
          ns ? (
            <span className="rounded-full bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] px-2.5 py-1 text-[10px] font-semibold text-[var(--primary)]">
              {t(ACTION_KEY[ns.action] ?? "Continue")}
            </span>
          ) : undefined
        }
      />
      <div className="flex flex-col gap-1.5 px-4 pb-5 pt-1">
        {ns ? (
          <>
            <strong className="text-[15px] tracking-tight text-[var(--foreground)]">
              {ns.knowledgePointName}
            </strong>
            <span className="text-[11px] text-[var(--muted-foreground)]">
              {typeLabel(ns.knowledgeType)} · {ns.pathName}
            </span>
            {ns.gate > 0 && (
              <GateMeter
                pct={ns.mastery * 100}
                gate={ns.gate * 100}
                color="var(--primary)"
                scale={`${Math.round(ns.mastery * 100)}% · ${t("gate")} ${Math.round(ns.gate * 100)}%`}
              />
            )}
            <button
              onClick={onGo}
              className="mt-2 self-start rounded-md bg-[var(--primary)] px-3 py-2 text-[11px] font-semibold text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
            >
              {t("Continue")} ↗
            </button>
          </>
        ) : (
          <p className="py-2 text-center text-[11px] text-[var(--muted-foreground)]">
            {t("Complete")}
          </p>
        )}
      </div>
    </Card>
  );
}

// --- activity: recent quiz answers ------------------------------------------
const ERROR_KEY: Record<string, string> = {
  structural: "Structural",
  deviation: "Misunderstanding",
  application: "Application",
  metacognitive: "Metacognitive",
};

function agoLabel(seconds: number): string {
  const m = Math.max(0, Math.round(seconds / 60));
  if (m < 60) return `${m}m`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h`;
  return `${Math.round(h / 24)}d`;
}

function QuizLogCard({
  dash,
  t,
  now,
}: {
  dash: PetDashboard | null;
  t: Tr;
  now: number;
}) {
  const items = dash?.quizLog ?? [];
  return (
    <Card>
      <CardHead title={t("Mastery Path answers")} />
      <ul className="px-4 pb-4">
        {items.length === 0 && (
          <li className="py-3 text-center text-[11px] text-[var(--muted-foreground)]">
            {t("No quiz answers yet")}
          </li>
        )}
        {items.map((q, i) => (
          <li
            key={`${q.knowledgePointId}:${q.timestamp}:${i}`}
            className="grid grid-cols-[34px_minmax(0,1fr)_auto] items-center gap-2.5 border-t border-[var(--border)] py-2.5 first:border-t-0"
          >
            <span
              className="grid h-[34px] w-[34px] place-items-center rounded-lg border border-[var(--border)] bg-[var(--background)] text-base"
              style={{
                color: q.isCorrect ? "var(--primary)" : "var(--destructive)",
              }}
            >
              {q.isCorrect ? "✓" : "×"}
            </span>
            <div className="min-w-0">
              <strong className="block truncate text-[11px] text-[var(--foreground)]">
                {q.name}
              </strong>
              <span className="block truncate text-[10px] text-[var(--muted-foreground)]">
                {q.isCorrect
                  ? q.pathName
                  : `${t(ERROR_KEY[q.errorType ?? ""] ?? q.errorType ?? "")} · ${t("ready to retry")}`}
              </span>
            </div>
            <span
              className="whitespace-nowrap text-right text-[10px] font-semibold"
              style={{
                color: q.isCorrect ? "var(--primary)" : "var(--destructive)",
              }}
            >
              {q.isCorrect ? t("Correct") : t("Incorrect")}
              <br />
              {agoLabel(now - q.timestamp)}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

// --- reviews ----------------------------------------------------------------
function dueLabel(seconds: number, t: Tr): string {
  const m = Math.round(seconds / 60);
  if (m < 60) return `${m}m`;
  if (m < 1440) return `${Math.round(m / 60)}h`;
  if (m < 2880) return t("Tomorrow");
  return `${Math.round(m / 1440)}d`;
}

function ReviewsCard({
  dash,
  typeLabel,
  t,
  now,
  onReview,
}: {
  dash: PetDashboard | null;
  typeLabel: (type: string) => string;
  t: Tr;
  now: number;
  onReview: () => void;
}) {
  const items = dash?.reviews ?? [];
  return (
    <Card>
      <CardHead
        title={t("Reviews")}
        right={<Pill>{dash?.reviewsDueCount ?? 0}</Pill>}
      />
      <ul className="px-4">
        {items.length === 0 && (
          <li className="flex flex-col items-center gap-2 py-6 text-center">
            <Image
              src="/anima/reviews-clipboard.png"
              alt=""
              width={512}
              height={446}
              className="h-auto w-[104px] select-none"
              draggable={false}
              priority={false}
            />
            <span className="text-[11px] text-[var(--muted-foreground)]">
              {t("No reviews due")}
            </span>
          </li>
        )}
        {items.map((r, i) => (
          <li
            key={`${r.knowledgePointId}:${i}`}
            className="grid grid-cols-[34px_minmax(0,1fr)_auto] items-center gap-2.5 border-t border-[var(--border)] py-2.5 first:border-t-0"
          >
            <span className="grid h-[34px] w-[34px] place-items-center rounded-lg border border-[var(--border)] bg-[var(--background)] text-[var(--muted-foreground)]">
              <RotateCw className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <strong className="block truncate text-[11px] text-[var(--foreground)]">
                {r.name}
              </strong>
              <span className="block truncate text-[10px] text-[var(--muted-foreground)]">
                {r.isDue ? `${t("Due now")} · ` : ""}
                {typeLabel(r.knowledgeType)}
                {r.weak && (
                  <b className="ml-1 rounded-full bg-[color-mix(in_srgb,var(--destructive)_15%,transparent)] px-1.5 py-px text-[9px] font-semibold text-[var(--destructive)]">
                    {t("Weak point")}
                  </b>
                )}
              </span>
            </div>
            <span
              className="whitespace-nowrap text-right text-[10px] font-semibold"
              style={{
                color: r.isDue
                  ? "var(--destructive)"
                  : "var(--muted-foreground)",
              }}
            >
              {r.isDue ? t("Now") : dueLabel(r.dueAt - now, t)}
            </span>
          </li>
        ))}
      </ul>
      <div className="p-4 pt-3">
        <button
          onClick={onReview}
          className="w-full rounded-md border border-[color-mix(in_srgb,var(--primary)_35%,var(--border))] bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] px-3 py-2 text-xs font-semibold text-[var(--primary)] transition-opacity hover:opacity-90"
        >
          {t("Review now")} ↗
        </button>
      </div>
    </Card>
  );
}

// --- paths ------------------------------------------------------------------
function PathsCard({
  dash,
  t,
  onManage,
}: {
  dash: PetDashboard | null;
  t: Tr;
  onManage: () => void;
}) {
  const paths = dash?.paths ?? [];
  return (
    <Card>
      <CardHead
        title={t("Mastery Path overview")}
        action={{ label: t("Manage paths"), onClick: onManage }}
      />
      <div className="grid grid-cols-1 gap-2.5 px-4 pb-4 sm:grid-cols-2 lg:grid-cols-3">
        {paths.map((p) => {
          const pct = p.total ? Math.round((p.mastered / p.total) * 100) : 0;
          return (
            <div
              key={p.pathId}
              className="rounded-[10px] border border-[var(--border)] bg-[var(--background)] p-3"
            >
              <div className="flex items-center gap-2">
                <span
                  className="grid h-7 w-7 shrink-0 place-items-center rounded-full"
                  style={{
                    background:
                      "color-mix(in srgb, var(--primary) 14%, transparent)",
                    color: "var(--primary)",
                  }}
                >
                  <GraduationCap className="h-3.5 w-3.5" />
                </span>
                <strong className="min-w-0 flex-1 truncate text-[11px] text-[var(--foreground)]">
                  {p.name}
                </strong>
              </div>
              <span className="mt-2 block text-[9px] text-[var(--muted-foreground)]">
                {t("{{mastered}}/{{total}} mastered", {
                  mastered: p.mastered,
                  total: p.total,
                })}
                {p.dueReviews > 0 &&
                  ` · ${t("{{n}} due", { n: p.dueReviews })}`}
              </span>
              <div className="mt-2.5 h-[5px] overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--foreground)_9%,transparent)]">
                <div
                  className="h-full rounded-full bg-[var(--primary)]"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

// --- shortcuts --------------------------------------------------------------
function ShortcutsCard({
  t,
  router,
}: {
  t: Tr;
  router: ReturnType<typeof useRouter>;
}) {
  const items: [ReactNode, string, string][] = [
    [<Map key="mp" className="h-4 w-4" />, t("Mastery Path"), NAV.learn],
    [<BookIcon key="bk" className="h-6 w-6" />, t("Books"), NAV.book],
    [<PenLine key="cw" className="h-4 w-4" />, t("Co-Writer"), NAV.coWriter],
    [<Users key="pt" className="h-4 w-4" />, t("Partners"), NAV.partners],
  ];
  return (
    <Card>
      <CardHead title={t("Shortcuts")} />
      <div className="grid grid-cols-2 gap-2.5 px-4 pb-4">
        {items.map(([icon, label, href]) => (
          <button
            key={label}
            onClick={() => router.push(href)}
            className="flex min-h-[48px] items-center gap-2.5 rounded-[10px] border border-[var(--border)] bg-[var(--background)] p-2.5 text-[10px] text-[var(--foreground)] transition-colors hover:border-[var(--primary)]"
          >
            <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] text-[var(--primary)]">
              {icon}
            </span>
            {label}
          </button>
        ))}
      </div>
    </Card>
  );
}
