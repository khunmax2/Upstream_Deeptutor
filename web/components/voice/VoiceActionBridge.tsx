"use client";

// Bridge for voice actions that need workspace-owned state.
//
// The call widget lives in the ROOT layout (so a live call survives
// navigation) — but some actions belong to providers mounted deeper, e.g.
// "new chat" must reset UnifiedChatContext, not just change the URL. The
// widget therefore dispatches a window CustomEvent for in-page actions and
// this bridge, mounted inside the workspace provider tree, executes them
// with the real store functions.
//
// Contract: the widget marks the event handled via `detail.handled()`; when
// no bridge is mounted (caller is on a non-workspace page) the widget falls
// back to plain navigation, which is correct there — a fresh workspace mount
// starts on a fresh draft session (URL is the session source of truth).
//
// Fork-additive: own file; mounted with a one-line include in the workspace
// layout, mirroring how VoiceCallWidget is mounted in the root layout.

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useUnifiedChat } from "@/context/UnifiedChatContext";

export const VOICE_ACTION_EVENT = "deeptutor:voice-action";

export interface VoiceActionDetail {
  target: string;
  argument?: string;
  handled?: () => void;
}

export default function VoiceActionBridge() {
  const router = useRouter();
  const { newSession, cancelStreamingTurn, sendMessage } = useUnifiedChat();

  useEffect(() => {
    const onAction = (ev: Event) => {
      const detail = (ev as CustomEvent<VoiceActionDetail>).detail;
      if (!detail) return;
      if (detail.target === "new_chat") {
        detail.handled?.();
        // Same sequence as the sidebar's New Chat button: never inherit a
        // still-running turn, then a fresh draft session on /home.
        cancelStreamingTurn();
        newSession();
        router.push("/home");
      } else if (detail.target === "type_in_chat") {
        // Secretary mode: the dictated utterance becomes a real chat turn in
        // the current session — full on-screen answer, persisted history.
        const text = (detail.argument || "").trim();
        if (!text) return;
        detail.handled?.();
        sendMessage(text);
        router.push("/home"); // make sure the caller sees what was typed
      }
    };
    window.addEventListener(VOICE_ACTION_EVENT, onAction);
    return () => window.removeEventListener(VOICE_ACTION_EVENT, onAction);
  }, [cancelStreamingTurn, newSession, router, sendMessage]);

  return null;
}
