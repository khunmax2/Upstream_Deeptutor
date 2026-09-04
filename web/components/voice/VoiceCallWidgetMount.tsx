"use client";

import dynamic from "next/dynamic";

/**
 * Client-side mount point for the voice call widget.
 *
 * The widget is a floating call button nobody has pressed on first paint, but
 * it pulls in the DOM-tree engine and the page actuator — together the largest
 * client chunk in the app. Importing it from the root layout put the shell
 * 124KB over the route budget v1.6.3 introduced, and cost every page load for a
 * feature most loads never use.
 *
 * `ssr: false` is only legal inside a Client Component, which is the whole
 * reason this one-line wrapper exists: `app/layout.tsx` is a Server Component.
 * The widget touches nothing but browser APIs (mic, speech, canvas), so there
 * is nothing to render on the server anyway.
 *
 * The call button is parked for now: `NEXT_PUBLIC_VOICE_CALL` gates it, and it
 * stays off unless that variable is set to `1`/`true`. Returning before the
 * dynamic import means the chunk is never requested either, so a disabled
 * build pays nothing for it.
 */
const VOICE_CALL_ENABLED = ["1", "true"].includes(
  (process.env.NEXT_PUBLIC_VOICE_CALL ?? "").toLowerCase(),
);

const VoiceCallWidget = dynamic(() => import("./VoiceCallWidget"), {
  ssr: false,
});

export default function VoiceCallWidgetMount() {
  if (!VOICE_CALL_ENABLED) return null;
  return <VoiceCallWidget />;
}
