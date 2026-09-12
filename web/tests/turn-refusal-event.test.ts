import assert from "node:assert/strict";
import test from "node:test";

import { refusalToStreamEvent } from "../features/chat/transport/UnifiedTurnClient";
import type { ServerEvent } from "../features/chat/model/protocol";

// Fork. The router's `protocol_error` used to vanish between the socket and
// the chat state: the adapter only understands stream events, so a refused
// start_turn left the assistant "reasoning…" forever. The bridge now renders a
// refusal as the terminal error event the adapter already ends a turn on.

test("a protocol_error becomes a terminal, failed error event carrying the message", () => {
  const event = refusalToStreamEvent({
    type: "protocol_error",
    error_code: "invalid_command",
    message: "Command does not match the turn protocol.",
    retryable: false,
    session_id: "s1",
    turn_id: "",
  } as unknown as ServerEvent);
  assert.ok(event);
  assert.equal(event.type, "error");
  assert.equal(event.content, "Command does not match the turn protocol.");
  assert.equal(event.metadata.turn_terminal, true);
  assert.equal(event.metadata.status, "failed");
  assert.equal(event.metadata.reason, "protocol_error:invalid_command");
  assert.equal(event.metadata.error_code, "invalid_command");
  assert.equal(event.metadata.retryable, false);
  assert.equal(event.session_id, "s1");
  assert.equal(event.turn_id, undefined);
});

test("a start_turn rejection from the runtime is the same shape", () => {
  const event = refusalToStreamEvent({
    type: "protocol_error",
    error_code: "start_turn_rejected",
    message: "A turn is already running on this session.",
    retryable: true,
  } as unknown as ServerEvent);
  assert.ok(event);
  assert.equal(event.metadata.reason, "protocol_error:start_turn_rejected");
  assert.equal(event.metadata.retryable, true);
});

test("a refusal with no message still says something a person can read", () => {
  const event = refusalToStreamEvent({
    type: "protocol_error",
    error_code: "",
    message: "",
    retryable: false,
  } as unknown as ServerEvent);
  assert.ok(event);
  assert.equal(event.content, "The server refused this request.");
  assert.equal(event.metadata.reason, "protocol_error:protocol_error");
});

test("anything that is not a refusal is left to the stream path", () => {
  assert.equal(
    refusalToStreamEvent({
      type: "command_ack",
      command_type: "start_turn",
      accepted: true,
    } as unknown as ServerEvent),
    null,
  );
  assert.equal(
    refusalToStreamEvent({ type: "pong" } as unknown as ServerEvent),
    null,
  );
  assert.equal(
    refusalToStreamEvent({
      type: "content",
      content: "hi",
    } as unknown as ServerEvent),
    null,
  );
});
