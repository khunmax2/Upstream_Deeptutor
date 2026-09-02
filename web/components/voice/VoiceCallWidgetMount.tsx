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
 */
const VoiceCallWidget = dynamic(() => import("./VoiceCallWidget"), {
  ssr: false,
});

export default function VoiceCallWidgetMount() {
  return <VoiceCallWidget />;
}
