import test from "node:test";
import assert from "node:assert/strict";

import { decodeRouteParam } from "../lib/route-params";

// The bug this guards: a partner id minted before ids were forced to ASCII
// (e.g. "เพ-อนฉ-น") reaches useParams() percent-encoded. The api client encodes
// its argument, so without decoding first the request goes out double-encoded
// (%25E0%25B9%2580…) and the backend 404s — the detail page could not be
// opened, and so the partner could not be edited or deleted from the UI.
test("a percent-encoded non-ASCII id is decoded back to the real id", () => {
  const id = "เพ-อนฉ-น";
  assert.equal(decodeRouteParam(encodeURIComponent(id)), id);
});

test("decoding is what stops the api client double-encoding", () => {
  const id = "เพ-อนฉ-น";
  const fromUseParams = encodeURIComponent(id);
  // What the api client would send with, and without, the fix.
  assert.equal(encodeURIComponent(decodeRouteParam(fromUseParams)), fromUseParams);
  assert.notEqual(encodeURIComponent(fromUseParams), fromUseParams);
});

test("ASCII ids are untouched, so existing partners keep working", () => {
  for (const id of ["lineme", "test", "partner-c9f4f98a", "math-3d7018ad"]) {
    assert.equal(decodeRouteParam(id), id);
  }
});

test("decoding an already-decoded id is a no-op", () => {
  // Idempotent for id-shaped values: a decoded id carries no '%'.
  const id = "เพ-อนฉ-น";
  assert.equal(decodeRouteParam(decodeRouteParam(encodeURIComponent(id))), id);
});

test("a malformed sequence falls back to the raw value instead of throwing", () => {
  assert.equal(decodeRouteParam("100%"), "100%");
  assert.equal(decodeRouteParam("%zz"), "%zz");
});

test("missing params collapse to an empty string", () => {
  assert.equal(decodeRouteParam(undefined), "");
  assert.equal(decodeRouteParam(null), "");
  assert.equal(decodeRouteParam(""), "");
});
