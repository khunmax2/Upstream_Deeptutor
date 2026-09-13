// Fork. Which GeoGebra commands the applet actually rejected.
//
// evalCommand's return value cannot be read at face value: measured
// 2026-09-13 in the real applet, a scripting command that took effect
// (SetColor, SetPointSize, ShowLabel, SetValue, SetCoords, SetCaption,
// SetLabelMode) returns false, while a construction command returns true on
// success and false when GeoGebra refuses it ("Unknown command",
// "Illegal argument", "Undefined variable"). A false from a scripting command
// is therefore not a failure; a false or a throw from anything else is.

const SCRIPTING_COMMAND =
  /^\s*(?:Set|Show|Hide|Zoom|Center|Delete|Rename|Update|Start|Stop|Pan|Play)[A-Za-z]*\s*[[(]/;

export function isScriptingCommand(command: string): boolean {
  return SCRIPTING_COMMAND.test(command);
}

/** True when evalCommand's outcome means GeoGebra refused the command. */
export function wasRejected(
  command: string,
  outcome: { returned?: unknown; threw?: boolean },
): boolean {
  if (outcome.threw) return true;
  if (outcome.returned !== false) return false;
  return !isScriptingCommand(command);
}
