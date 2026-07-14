// Anima Habitat — pet bridge client.
// Mirrors deeptutor/api/routers/pet.py. The server is authoritative: this client
// only READS state (and can post mock events); it never computes pet stats.

import { apiUrl, apiFetch } from "./api";

export interface PetState {
  petId: string;
  name: string;
  element: string;
  level: number;
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

/** Authoritative pull: the server applies decay + drains new mastery signal. */
export async function fetchPetState(pathId: string): Promise<PetState> {
  const res = await apiFetch(
    apiUrl(`/api/v1/pet/state?pathId=${encodeURIComponent(pathId)}`),
  );
  if (!res.ok) throw new Error(`Failed to fetch pet state: ${res.status}`);
  return res.json() as Promise<PetState>;
}

/** Manual/mock event (demo + debugging; real signal comes from mastery grading). */
export async function postPetEvent(
  pathId: string,
  event: PetEventType,
  decayAmount = 0,
): Promise<PetState> {
  const res = await apiFetch(apiUrl(`/api/v1/pet/event`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      path_id: pathId,
      event,
      decay_amount: decayAmount,
    }),
  });
  if (!res.ok) throw new Error(`Failed to post pet event: ${res.status}`);
  return res.json() as Promise<PetState>;
}
