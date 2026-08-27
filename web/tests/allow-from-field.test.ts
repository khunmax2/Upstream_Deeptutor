import test from "node:test";
import assert from "node:assert/strict";

import { modeOf, valueForMode } from "../components/partners/AllowFromField";

test("the three states map to the values the backend checks", () => {
  // channels/base.py: empty list denies everyone, "*" short-circuits to allow.
  assert.equal(modeOf([]), "none");
  assert.equal(modeOf(["*"]), "everyone");
  assert.equal(modeOf(["U123"]), "list");
});

test("a wildcard mixed into a list still means everyone", () => {
  // is_allowed returns True as soon as it sees "*", whatever else is listed —
  // showing this as a restricted list would misrepresent who gets through.
  assert.equal(modeOf(["U123", "*"]), "everyone");
});

test("switching to everyone or none writes the exact expected value", () => {
  assert.deepEqual(valueForMode("everyone", ["U123"]), ["*"]);
  assert.deepEqual(valueForMode("none", ["U123"]), []);
});

test("listed senders survive a round trip through everyone", () => {
  // Toggling to "anyone" and back must not silently discard the allow-list.
  const original = ["U123", "U456"];
  const opened = valueForMode("everyone", original);
  assert.deepEqual(valueForMode("list", original), original);
  assert.equal(modeOf(opened), "everyone");
});

test("the wildcard is stripped when returning to a restricted list", () => {
  // Otherwise the list would still contain "*" and keep letting everyone in.
  assert.deepEqual(valueForMode("list", ["U123", "*"]), ["U123"]);
  assert.equal(modeOf(valueForMode("list", ["U123", "*"])), "list");
});

test("returning to an empty list stays deny-all rather than opening up", () => {
  assert.deepEqual(valueForMode("list", ["*"]), []);
  assert.equal(modeOf(valueForMode("list", ["*"])), "none");
});
