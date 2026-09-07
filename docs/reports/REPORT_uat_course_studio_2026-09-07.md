# UAT — the course studio, end to end — 2026-09-07

**Branch:** `feat/openmaic-subtree` · local only
**Scope:** every clickable control on the reachable surfaces, plus a course
built from an empty library to a playing classroom
**Outcome:** 11 defects found and fixed · 6 found and reported · 5 things that
looked like defects and are not

---

## How it was tested

Clicking screenshots is a poor way to prove a negative, so the sweep was
mechanical wherever it could be:

| Method | What it covered |
|---|---|
| Server HTML fetch of every page route | brand strings, external links, page titles |
| Real `pointerdown`/`pointerup`/`click` on every visible button, then a DOM scan of what appeared | 15 home controls, 10 settings tabs, 19 classroom controls |
| Static audit of all 1 699 `t()` calls against both locale tables | keys called but never defined |
| Regex sweep for CJK literals outside locale files, prompts and comments | hardcoded Chinese |
| A real course: Thai prompt → outline → classroom → playback → export menu | the whole path a learner walks |

The click harness ran real pointer events rather than `element.click()`, because
Radix menus listen on `pointerdown` and a synthetic `click` silently does
nothing — an early pass wrongly looked like a dead language button.

---

## Fixed

### 1. The Chinese toast on the microphone — the symptom originally reported

Pressing the mic and denying permission produced

    无法访问麦克风，请检查权限设置

in every language. `lib/hooks/use-audio-recorder.ts` carried **nine** hardcoded
Chinese messages — no speech detected, mic unavailable, permission denied,
network error, recognition failed, and the rest. All nine now go through `t()`,
translated into 13 languages.

### 2. `defaultLocale` was `zh-CN` — and it is both `lng` and `fallbackLng`

`lib/i18n/types.ts` set the app's default locale to Chinese, and
`lib/i18n/config.ts` feeds that same value to i18next as **both** the starting
language and the fallback. Two consequences, neither obvious:

- the first paint was Chinese until the client resolved a language;
- **any key missing from a locale fell back to Chinese**, not to English.

Now `en-US` — the language every locale file is written against.

### 3. Azure TTS was told to pronounce everything in Chinese

`lib/audio/tts-providers.ts` built its SSML with `xml:lang='zh-CN'` hardcoded, on
both the `<speak>` and the `<voice>` element. An Azure voice is named for its
locale (`th-TH-PremwadeeNeural`), so the tag now comes from the voice id.

### 4. Two more `|| 'zh-CN'` speech defaults

`components/settings/asr-settings.tsx` and `lib/hooks/use-browser-asr.ts` both
fell back to Chinese for browser speech recognition. Both now follow the
browser's own locale. `lib/hooks/use-browser-tts.ts` had the same default plus
its own Chinese error string; it now follows the UI language.

### 5. `stage.proMode` was called and defined nowhere

`components/stage/header-controls.tsx:123` renders `{t('stage.proMode')}` as the
label beside the Pro switch. The key existed in **no locale** — the reader saw
the literal string `stage.proMode`. Added in 13 languages. Missing since before
this work; the upstream key gate only checks that locales agree with each other,
never that a `t()` call resolves, so nothing caught it.

### 6. English tooltips in the Thai classroom

Six transport controls carried hardcoded English `aria-label`s — *Play*,
*Mute*, *Previous scene*, *Next scene*, *Auto-play*, *Playback speed*,
*Toggle chat*, *Toggle sidebar* — beside neighbours that were properly
translated. Now translated in 13 languages.

### 7. A dead panel written entirely in Chinese

`components/agent/agent-config-panel.tsx` — 11 Chinese strings including a
`confirm()` — is imported by nothing. Deleted.

### 8–11. The host's own frame, and four smaller things

- `MaicWorkspace.tsx` said **"OpenMAIC course studio"** in the panel header, the
  iframe's accessible name, and the new-tab tooltip; the sidebar tooltip said
  "Build a whole course with OpenMAIC"; the voice widget's page list named
  OpenMAIC in Thai. All de-branded, in en/th/zh.
- The route `/maic` is now **`/course-studio`**, with a **308** redirect so old
  links still land.
- The brand substitution from earlier today had left a space behind in ja/th/zh
  (`ให้ เอเจนต์`, `エージェント に`, `智能体 生成`) — those languages do not space
  words. Closed.

---

## Found, not fixed — these need a decision

| # | Finding | Why it was left |
|---|---|---|
| 1 | **43 Chinese strings in the slide editor** — `EditableElement.tsx` (25, the right-click menu: cut/copy/paste/align/layer/lock), `Canvas/index.tsx` (9), `LinePresetPicker.tsx` (8) | Behind `NEXT_PUBLIC_MAIC_EDITOR_ENABLED`, off by default. Dormant, but it is the largest remaining pocket. |
| 2 | **`defaultWorkbenchTranslator = createWorkbenchTranslator('zh-CN')`** — the Pro workbench's hook-free translator. ~45 call sites take it as a default parameter, and 7 module-level constants are frozen in Chinese at import time | Behind the Pro workbench flag, off by default. Two test files assert its Chinese output. |
| 3 | **13 more hardcoded English `aria-label`s** outside the classroom toolbar (editor, chat, attachments) | Same class as #6 above, on surfaces a learner does not reach. |
| 4 | **Buttons with no accessible name** — the home page's language / theme / settings icons, and 4 classroom controls | A screen reader announces nothing for these. |
| 5 | `quiz-view.tsx` and `pbl/v2/submission.tsx` branch `zh-CN ? Chinese : English` | Not a Chinese leak — a Thai reader gets English — but not translated either. |
| 6 | **TTS is not carried by the provider bridge** | See below. |

### On #6 — why new courses have no narration

`server-providers.yml` reports `1 LLM, 0 TTS, 1 ASR, 0 PDF, 0 Image, 0 Video, 1 WebSearch`.

That zero is deliberate and it is still a gap. OpenMAIC's `ServerProviderEntry`
carries `apiKey`, `baseUrl`, `models`, `proxy` and `enabled` — and **no voice
field**. The configured speech server's only voice is `dr_wit`, so emitting the
entry produced a provider that OpenMAIC then called with its built-in default
`alloy` and got `Bad Request`; worse, it was auto-selected ahead of anything
that worked. Skipping it was right. But nothing takes its place.

The consequence is invisible until you look from a fresh browser: TTS settings
live in the studio's own per-browser store, so **the machine that configured it
once still has speech, and every other browser and every new user has none.**
Either the operator configures TTS once per browser, or the deployment uses a
speech provider whose default voice is usable — the bridge cannot express the
third option.

---

## Looked like defects, and are not

- **Chinese Azure voice names** (`晓晓 (女)`, `云希 (男)`) — the provider's own
  names for its voices; translating them would stop them matching Azure's docs.
- **`火山方舟 Agent Plan`** in the token-package tab — ByteDance's platform name.
- **The language menu's Chinese entries** — endonyms. `简体中文` is what Simplified
  Chinese is called in Simplified Chinese, and all 13 including `ไทย` are correct.
- **`lib/server/agent-runtime/fetch-url.ts`** — Chinese strings there are markers
  *matched against* scraped pages, never displayed.
- **`/workbench/new` returning 404** — the Pro workbench flag is off. Correct.

---

## The end-to-end run

Prompt (Thai): *สอนการบวกเลขเบื้องต้นสำหรับเด็ก ป.1 ใน 5 นาที*

| Step | Result |
|---|---|
| Outline generation | Thai throughout — *"กำลังร่างโครงคอร์ส"*, *"เอเจนต์ AI กำลังทำงาน…"* |
| Classroom created | `/classroom/bLbDNdr_JP` |
| Slide content | Thai only — headings, bullets, teacher name *ครูใจดี* |
| Narration text | Thai, no language mixing |
| Playback | Play → Pause, progress advanced 1/4 → 1/7 |
| Export menu | 4 options, all Thai |
| Server errors during the run | **none** |

The mixed-language output seen earlier did not recur.

---

## Leak scan — every surface, every check

| Surface | brand | external links | raw i18n keys | Chinese |
|---|---|---|---|---|
| `/` | 0 | 0 | 0 | 0 |
| `/workspace` | 0 | 0 | 0 | 0 |
| `/generation-preview` | 0 | 0 | 0 | 0 |
| `/eval/whiteboard` | 0 | 0 | 0 | 0 |
| `/classroom/:id` | 0 | 0 | 0 | 0 |
| Settings — all 10 tabs | 0 | 0 | 0 | only `火山方舟` (a product name) |
| Export menu | 0 | 0 | 0 | 0 |
| Host `/course-studio` | 0 | — | — | — |

`/maic` → **308** → `/course-studio`. Old export files still import: the picker
accepts `.zip` and never compared against the renamed constant.

---

## Gates

| Check | Result |
|---|---|
| `tsc --noEmit` | clean |
| `eslint` on every changed file | clean |
| `check-i18n-keys.mjs` | 13 locale files |
| `check_openmaic_contract.py` | all checks passed |
| `npm run test:node` (DeepTutor) | **1105 / 1105** |
| vitest — i18n + audio + speech-button | 9 files passed |
| `docker compose build` (both images) | exit 0 |

Two vitest files stayed red and neither is from this work:
`audio-player-leak.test.ts` exercises `lib/utils/audio-player`, which nothing
here touches, and `narrator-pin-fallback.test.ts` is the known upstream flake.
`element-reference-route-l2.test.ts` failed **5/5 on a pristine worktree at
HEAD** and 4/5 with these changes.

---

## Still open

1. **Rotate the exposed API keys** — Gemini, Groq, Tavily and OpenRouter have all
   appeared in this session's transcript. Oldest open item.
2. Decide on the six reported findings above, especially the slide-editor
   Chinese (#1) and how TTS should reach a new browser (#6).
3. The upstream-candidate patches: the audio-recorder i18n, the `zh-CN`
   defaults, `stage.proMode` and the aria-labels are plain bugs for anyone, not
   integration work.
