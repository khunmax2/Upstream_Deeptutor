"use client";

import dynamic from "next/dynamic";

/**
 * Client-side mount point for the voice action bridge.
 *
 * Same reasoning as VoiceCallWidgetMount: the bridge renders nothing — it only
 * listens for voice action events and drives the chat runtime — so there is no
 * first-paint cost worth paying for it, and deferring keeps the shared shell
 * inside the route budget. It is also browser-only by nature.
 */
const VoiceActionBridge = dynamic(() => import("./VoiceActionBridge"), {
  ssr: false,
});

export default function VoiceActionBridgeMount() {
  return <VoiceActionBridge />;
}
