import test from "node:test";
import assert from "node:assert/strict";

import { isScriptingCommand, wasRejected } from "../lib/ggb-commands";

// Fork. The outcomes below are what the real GeoGebra applet returned from
// evalCommand for these commands (2026-09-13): scripting commands return false
// even when they worked, so only a false from a construction command, or a
// throw, may be reported as a rejection.

test("a scripting command that returned false is not a rejection", () => {
  for (const command of [
    'SetColor[V, "#D62728"]',
    "SetPointSize[A, 5]",
    "ShowLabel[P, true]",
    "SetValue[t, 2]",
    "SetCoords[Text1,0,6]",
    'SetCaption[n,"n"]',
    "SetLabelMode[V, 1]",
    "ZoomIn(-1, -1, 5, 5)",
  ]) {
    assert.equal(isScriptingCommand(command), true, command);
    assert.equal(wasRejected(command, { returned: false }), false, command);
  }
});

test("a construction command that returned false is a rejection", () => {
  for (const command of [
    "Ecliptic = InfinitePlane[(0,0,0), (1,0,0), (0,1,0)]",
    "T1=Sequence[Sequence[Point[i,j],i,1,j],j,1,n]",
    "L3 = Sequence[Sequence[(i, j), j = 1, i], i = 1, n]",
    "f(x) = x^2",
  ]) {
    assert.equal(isScriptingCommand(command), false, command);
    assert.equal(wasRejected(command, { returned: false }), true, command);
  }
});

test("a command that succeeded or threw is judged by that", () => {
  assert.equal(wasRejected("A = (1, 2)", { returned: true }), false);
  assert.equal(wasRejected("A = (1, 2)", { returned: undefined }), false);
  assert.equal(wasRejected('SetColor[A, "#000000"]', { threw: true }), true);
});

test("a label that merely starts like a scripting verb is not one", () => {
  // "Settle" and "Shower" are object names, not SetX/ShowX commands.
  assert.equal(isScriptingCommand("Settle = (1, 2)"), false);
  assert.equal(isScriptingCommand("Shower = Circle[(0,0), 1]"), false);
});
