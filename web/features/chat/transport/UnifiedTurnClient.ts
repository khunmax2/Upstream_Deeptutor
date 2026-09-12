import type {
  ClientCommand,
  ServerEvent,
} from "@/contracts/generated/turn-protocol";

import type {
  ChatMessage,
  StreamEvent,
  StreamEventType,
} from "../model/protocol";
import {
  TurnRuntimeClient,
  type RuntimeConnectionState,
} from "./TurnRuntimeClient";

const STREAM_TYPES = new Set<StreamEventType>([
  "stage_start",
  "stage_end",
  "thinking",
  "observation",
  "content",
  "tool_call",
  "tool_result",
  "progress",
  "sources",
  "result",
  "error",
  "session",
  "session_meta",
  "wait_for_input",
  "done",
]);

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : {};
}

function toStreamEvent(event: ServerEvent): StreamEvent | null {
  const raw = event as unknown as Record<string, unknown>;
  const type = raw.type;
  if (typeof type !== "string" || !STREAM_TYPES.has(type as StreamEventType))
    return null;
  return {
    type: type as StreamEventType,
    source: typeof raw.source === "string" ? raw.source : "",
    stage: typeof raw.stage === "string" ? raw.stage : "",
    content: typeof raw.content === "string" ? raw.content : "",
    metadata: asRecord(raw.metadata),
    session_id: typeof raw.session_id === "string" ? raw.session_id : undefined,
    turn_id: typeof raw.turn_id === "string" ? raw.turn_id : undefined,
    seq: typeof raw.seq === "number" ? raw.seq : undefined,
    timestamp:
      typeof raw.timestamp === "number" ? raw.timestamp : Date.now() / 1000,
  };
}

/**
 * Fork. A refusal at the socket must end the turn on screen.
 *
 * The router answers a command it cannot accept with `protocol_error`
 * (`invalid_command` when the payload fails the wire schema,
 * `start_turn_rejected` when the runtime declines it). That is not a stream
 * event, so `toStreamEvent` drops it and the adapter never hears that the
 * turn it optimistically started will never run: the transcript shows the
 * question, the assistant shows "reasoning…", and nothing ever changes it.
 * Found 2026-09-12 when every turn on a YouTube material was refused for a
 * viewport field the backend model did not know -- silently.
 *
 * Rendered as the terminal `error` event the adapter already handles (it
 * ends the stream as failed and shows the message in the transcript), so
 * the refusal reads like any other failed turn instead of a hang.
 */
export function refusalToStreamEvent(event: ServerEvent): StreamEvent | null {
  const raw = event as unknown as Record<string, unknown>;
  if (raw.type !== "protocol_error") return null;
  const code =
    typeof raw.error_code === "string" && raw.error_code.trim()
      ? raw.error_code.trim()
      : "protocol_error";
  const message =
    typeof raw.message === "string" && raw.message.trim()
      ? raw.message.trim()
      : "The server refused this request.";
  return {
    type: "error",
    source: "transport",
    stage: "",
    content: message,
    metadata: {
      turn_terminal: true,
      status: "failed",
      reason: `protocol_error:${code}`,
      error_code: code,
      retryable: raw.retryable === true,
    },
    session_id:
      typeof raw.session_id === "string" && raw.session_id
        ? raw.session_id
        : undefined,
    // The router fills these with "" when it has none; an empty id is no id.
    turn_id:
      typeof raw.turn_id === "string" && raw.turn_id ? raw.turn_id : undefined,
    seq: undefined,
    timestamp: Date.now() / 1000,
  };
}

type OutboundTurnCommand = ChatMessage | ClientCommand;

function command(message: OutboundTurnCommand): ClientCommand {
  if ("protocol_version" in message && message.protocol_version === "2.0") {
    return message as ClientCommand;
  }
  return { ...message, protocol_version: "2.0" } as ClientCommand;
}

/** Transitional surface API backed entirely by the validated v2 runtime. */
export class UnifiedTurnClient {
  private readonly runtime: TurnRuntimeClient;
  private connectionState: RuntimeConnectionState = "idle";
  private closeNotified = false;

  constructor(onEvent: (event: StreamEvent) => void, onClose?: () => void) {
    this.runtime = new TurnRuntimeClient({
      onEvent(event) {
        const streamEvent = toStreamEvent(event) ?? refusalToStreamEvent(event);
        if (streamEvent) onEvent(streamEvent);
      },
      onStateChange: (state) => {
        this.connectionState = state;
        if (state === "idle" && !this.closeNotified) {
          this.closeNotified = true;
          onClose?.();
        }
        if (state === "connected") this.closeNotified = false;
      },
    });
  }

  get connected(): boolean {
    return this.connectionState === "connected";
  }

  setResumeState(turnId: string | null, seq: number): void {
    this.runtime.setResumeCursor(turnId, seq);
  }

  connect(): void {
    this.runtime.connect();
  }

  send(message: OutboundTurnCommand): void {
    this.runtime.send(command(message));
  }

  /** Send, and resolve with whether the server accepted the command. */
  sendAwaitingAck(message: OutboundTurnCommand): Promise<boolean> {
    return this.runtime.sendAwaitingAck(command(message));
  }

  disconnect(): void {
    this.runtime.stop();
    this.runtime.setResumeCursor(null, 0);
    this.connectionState = "stopped";
  }
}
