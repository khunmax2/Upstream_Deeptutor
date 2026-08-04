// Learner Anima — pet bridge client.
// Mirrors deeptutor/api/routers/pet.py. The server is authoritative: this client
// only READS state (and can post mock events); it never computes pet stats.
// One pet per user (aggregate across all paths), so no pathId — the endpoints
// resolve the current user.

import { apiUrl, apiFetch } from "./api";

export interface PetState {
  petId: string;
  name: string;
  element: string;
  level: number;
  /** Evolution form (1..3), derived server-side from level vs `evolve_levels`. */
  stage: number;
  exp: number;
  expToNext: number;
  hunger: number;
  happy: number;
  sick: boolean;
  lastEvent: string;
  updatedAt: string;
}

export type PetEventType =
  "LEARN_CONCEPT" | "QUIZ_PASS" | "QUIZ_FAIL" | "REVIEW_DECAY";

// --- dashboard read model (mirrors deeptutor/pet/dashboard.py) ---------------
// One aggregate GET so the page never does N+1 reads across a user's paths.
export interface MasteryAxis {
  type: string; // "memory" | "concept" | "procedure" | "design"
  mastered: number;
  total: number; // 0 => render N/A, never 0%
}
export interface AlmostItem {
  knowledgePointId: string;
  name: string;
  knowledgeType: string;
  pathName: string;
  mastery: number;
  gate: number;
  attemptsNeeded: number;
}
export interface NextStep {
  action: string;
  knowledgePointName: string;
  knowledgeType: string;
  pathName: string;
  mastery: number;
  gate: number;
}
export interface GrowthSummary {
  almost: AlmostItem[];
  weakPointsCleared: number;
  weakPointsActive: number;
  nextStep: NextStep | null;
}
export interface QuizLogItem {
  knowledgePointId: string;
  name: string;
  pathName: string;
  isCorrect: boolean;
  errorType: string | null;
  timestamp: number;
}
export interface ReviewItem {
  knowledgePointId: string;
  name: string;
  knowledgeType: string;
  dueAt: number;
  isDue: boolean;
  weak: boolean;
}
export interface PathSummary {
  pathId: string;
  name: string;
  mastered: number;
  total: number;
  dueReviews: number;
}
export interface PetDashboard {
  pet: PetState;
  profile: MasteryAxis[];
  profileMastered: number;
  profileTotal: number;
  growth: GrowthSummary;
  reviews: ReviewItem[];
  reviewsDueCount: number;
  quizLog: QuizLogItem[];
  paths: PathSummary[];
}

/** Aggregated pull for the whole /anima page (pet + all-path learning view). */
export async function fetchPetDashboard(): Promise<PetDashboard> {
  const res = await apiFetch(apiUrl(`/api/v1/pet/dashboard`));
  if (!res.ok) throw new Error(`Failed to fetch pet dashboard: ${res.status}`);
  return res.json() as Promise<PetDashboard>;
}

/** Authoritative pull: the server applies decay + drains new mastery signal. */
export async function fetchPetState(): Promise<PetState> {
  const res = await apiFetch(apiUrl(`/api/v1/pet/state`));
  if (!res.ok) throw new Error(`Failed to fetch pet state: ${res.status}`);
  return res.json() as Promise<PetState>;
}

/** Manual/mock event (demo + debugging; real signal comes from mastery grading). */
export async function postPetEvent(
  event: PetEventType,
  decayAmount = 0,
): Promise<PetState> {
  const res = await apiFetch(apiUrl(`/api/v1/pet/event`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event, decay_amount: decayAmount }),
  });
  if (!res.ok) throw new Error(`Failed to post pet event: ${res.status}`);
  return res.json() as Promise<PetState>;
}
