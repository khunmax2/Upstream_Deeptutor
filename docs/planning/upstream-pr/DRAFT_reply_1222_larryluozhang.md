> **Draft reply to larryluozhang on HKUDS/DeepTutor#1222 — not posted.**
> Every claim checked against upstream `93df3d48` (v1.6.4).

```markdown
Thanks — #1 matches what I hit, and it generalises: the map has five entries
against thirty-four guarded routers, so _any_ path it does not name is denied by
construction. I mapped `/api/settings/llm-options` to `chat` for exactly that
reason (symptom 9 above) — the same shape as your `/api/knowledge-bases` and
`/api/mastery-paths`.

One thing worth checking before that workaround goes further, though: the
surfaces and the capabilities are two separate lists, and mapping only the first
moves the failure rather than removing it.

`learner_grant` declares:

    "allowed_capabilities": ["chat", "immersive_reading"],
    "allowed_surfaces":     ["chat", "reading"],

`mastery` is its own capability (`capabilities/registry.py`), and
`apply_learning_policy` runs on every turn from
`services/session/turns/request_preparer.py`:

    if capability not in allowed:
        raise PermissionError("This learning account cannot use this mode…")

So with `/api/mastery-paths → chat` the Mastery Path screens load, but starting a
session should still be refused at turn time — a 403 at the nav traded for a
PermissionError mid-session. Worth confirming on your deployment; if a mastery
session does run for you, then something else in your patch set is also relaxing
`allowed_capabilities`, and that is the change that actually grants the feature.

That is really a question for the maintainers rather than a correction: **should
a learner have Mastery Path and Knowledge Center at all?** The declared policy
says no. If the answer is yes, both lists need to move together plus whatever
`apply_learning_policy` strips (it also clears `tools`, `knowledge_bases` and
`enable_rag` on every turn). If the answer is no, the fix is the frontend not
offering them — which is symptom 1 in the report.

On #2 — agreed on the conclusion, with one detail from reading the code: in
v1.6.4 the account preset is read in three places only —
`app/(admin)/admin/users/page.tsx`,
`features/multi-user/components/GuardianRelationshipsEditor.tsx`, and
`features/settings/navigation/settings-access.ts`. Nothing in the app shell keys
off it, which is why the shell loads everything for _any_ non-admin and the 403
storm follows. Flipping `preset` to `learner` changes the two
settings sections (`learnerOnly` / `guardianOnly`) but not the shell, so if it
made the whole scoped UI appear for you, that is likely another patch in your
stack doing the work.

Your suggested direction is the one I took: key off `learning_policy` presence,
not `preset`, per #1111. In my build `settings-access` grows
`restricted: Boolean(authStatus.learning_policy)`, `useAuthStatus` carries
`allowed_surfaces` through, and both the sidebar and the settings categories
filter on it. An entry with no declared surface is hidden rather than shown, so a
feature added later stays out of a restricted account until someone checks its
endpoints. That removes the storm without needing the preset flip.

Happy to put any of it up as PRs if the maintainers want it in this shape.
```
