---
name: claude-md-writing
description: Author or edit a Claude instruction file so it stays high-signal and reliably followed. Use whenever the user asks to create, write, improve, trim, restructure, or review a CLAUDE.md / AGENTS.md (always-loaded memory), or a SKILL.md / subagent / .claude/rules agent-doc (on-demand). Applies the full instruction-budget + progressive-disclosure rules to always-loaded files, and a relaxed subset to on-demand files. Enforces WHAT/WHY/HOW structure and the "don't make the LLM do a linter's job" rule.
version: 1.0.0
---

# Writing a Good CLAUDE.md

`CLAUDE.md` is loaded into **every** session, verbatim, before the user says anything. It is the single most token-expensive and highest-leverage file in the repo: every line you add is paid for on every turn, of every conversation, forever. Treat it as a budget, not a wiki.

This skill governs how to write or edit `CLAUDE.md` (and the agent-docs it points to). Apply it whenever creating a new one, trimming a bloated one, or adding a rule to an existing one.

---

## First: Which Regime Is This File?

Not every Claude instruction file is loaded the same way, and the rules below apply **differently** depending on *when the file enters context*. Classify the file before applying anything.

| Regime | Files | When loaded | Budget pressure |
|--------|-------|-------------|-----------------|
| **A — Always-loaded** | `CLAUDE.md`, `AGENTS.md` (incl. nested + `@`-imports) | Verbatim, every session, before the user speaks | **Extreme** — every line is paid on every turn forever |
| **B — On-demand** | `SKILL.md` bodies, subagent `.claude/agents/*.md`, `.claude/rules/*.md`, any pointer-target agent-doc | Only when triggered / pulled in by a pointer; SKILL.md loads only its `name`+`description` upfront, body later | **Low** — paid only in sessions that actually use it |

**Rules 1 and 3 (the line budget, "subtraction is a feature", "remove two to add one", aggressive progressive disclosure) apply in FULL force to Regime A only.** A Regime-B file is itself the *target* of progressive disclosure — it is allowed to be long and detailed, because you only pay for it when it's relevant. Do not trim a SKILL.md or a rules file just to hit a line count.

**Rules 2, 4, 5, 6 (WHAT/WHY/HOW, no linter's-job, write-for-attention, craft-by-hand) apply to BOTH regimes** — every instruction file benefits from being clear, specific, lint-free, and hand-written.

The rest of this skill is written for Regime A (the hard case). When editing a Regime-B file, apply the cross-cutting rules and ignore the budget-specific ones.

---

## The One Mental Model

> Models have no memory between sessions. The only project knowledge that persists is the tokens in `CLAUDE.md`. But instruction-following degrades as instruction count rises — frontier models reliably honour ~150–200 instructions, and the harness system prompt already spends ~50 of them.

So every line competes for a scarce budget. The job is **maximum behavioural change per token**, not maximum coverage.

---

## Rule 1 — Stay Under Budget

- **Target under 300 lines. Aim much lower** — a tight 60–150 lines beats a thorough 400.
- Before adding anything, ask: *"Will this change Claude's behaviour in a meaningful fraction of sessions?"* If no, it does not belong — and if it's detail about one area (migrations, testing, a single app), it belongs in a `.claude/rules/*.md` file or skill with a one-line pointer here.
- Every instruction you add slightly degrades adherence to **all** the others. Adding a low-value rule actively makes the high-value rules less likely to be followed. Subtraction is a feature.
- If the file is already long, the right move when asked to "add a rule" is often to **remove two and rewrite one**, not append.

---

## Rule 2 — Cover WHAT, WHY, HOW (and nothing else)

A good `CLAUDE.md` answers three questions and stops:

| Element | Content | Example |
|---------|---------|---------|
| **WHAT** | Tech stack, project structure, codebase map (critical for monorepos) | "Django 4.2 + DRF backend, apps `events` and `users`, PostgreSQL required" |
| **WHY**  | Purpose of the project and of its non-obvious components | "`VideoAsset.save()` runs ffmpeg synchronously, so use `QuerySet.update()` for column-only writes" |
| **HOW**  | Operational commands — build, test, run, lint, migrate | "`pytest events/tests/test_apis.py` runs one test file; `tox -e quality` is the CI lint" |

Keep content **universally applicable across all sessions**. Task-specific or area-specific guidance (a particular schema, one module's quirks) does not belong in the always-loaded file — it belongs in an agent-doc (Rule 3).

---

## Rule 3 — Prefer Pointers to Copies (Progressive Disclosure)

This is the core technique for staying under budget without losing information.

- Keep detail in **separate markdown files** and leave a one-line pointer in `CLAUDE.md`.
  - e.g. `.claude/rules/backend-django.md`, `agent_docs/running_tests.md`, `agent_docs/deploy.md`
- The pointer states *when* to read the file, so Claude pulls it in only for relevant work:
  > For any change to models or migrations, read `.claude/skills/django-migration-standards/SKILL.md` first.
- **Prefer pointers to copies for code, too.** Reference `file_path:line` locations rather than pasting snippets — pasted code rots silently the moment the source changes; a pointer never lies.
- A table of `| file | scope |` pointers (as this repo's CLAUDE.md already uses for `.claude/rules/`) is the ideal shape: tiny in the always-loaded file, deep on demand.

---

## Rule 4 — Don't Send an LLM to Do a Linter's Job

- **Do not** encode mechanical code style in `CLAUDE.md` — indentation, quote style, import ordering, line length, trailing commas.
- These are deterministically enforced by linters/formatters (ESLint, ruff, prettier, black). A linter enforces them on 100% of lines for 0 tokens; an instruction enforces them probabilistically for a permanent token cost.
- Wire style into **hooks** (run the formatter on save / pre-commit) or **CI**, not into the prompt.
- The narrow exception: a *project-specific* convention a linter cannot express and that genuinely changes behaviour (e.g. "use `getLogger('asp_api')` — the only logger with handlers configured"). Even then, prefer a pointer to a rules file over inlining it.

> Reviewer heuristic: if a rule could be a lint rule, it should be — delete it from CLAUDE.md and open a linter-config task instead.

---

## Rule 5 — Write for the Model's Attention

- LLMs weight the **beginning and end** of a long document most heavily. Put the highest-stakes, must-never-violate rules at the top or bottom — not buried in the middle.
- Be **imperative and specific**: "Always create the migration in the same MR as the model change" beats "migrations are important".
- Use concrete ✅/❌ pairs for anything easy to get subtly wrong — a right-vs-wrong example carries more signal per token than a paragraph.
- One instruction per line/bullet. Don't bury three rules in a sentence; the model may honour one and drop two.

---

## Rule 6 — Craft It by Hand

- **Do not** auto-generate `CLAUDE.md` with `/init` and walk away. Auto-generated files are bloated, generic, and full of low-value WHAT that the model could infer from the code anyway.
- `/init` is acceptable only as a *first draft to ruthlessly cut*. The finished file should read like it was written by someone who knows which 10 things actually trip Claude up in this repo.
- Don't restate what the code already makes obvious. Spend the budget on the **non-obvious**: cross-module coupling, footguns, "looks wrong but is intentional", required commands.

---

## Rule 7 — Verify the Fact, and Mind the Altitude

Two failure modes that survive review because the prose *reads* well while the content is wrong or misplaced:

- **Verify before you enshrine.** Never lift a *rationale* from a code comment, docstring, or commit message into a CLAUDE.md without confirming it is actually true — against the code, or the system's owner. A comment's "why" is a claim, not ground truth; copied into always-loaded memory it outlives and out-travels the comment and misleads every future session. *(Real case: a migration docstring said a flag was consumed by an external export "which reads all rows"; the export only reads active rows, and the manager choice was actually forced by a migration constraint — `apps.get_model()` exposes no custom managers. Documenting the stated "why" would have enshrined a non-reason.)*
- **Document the invariant, not the mechanic.** The app-specific *invariant* (e.g. "`OverheadCost.is_direct_team_overhead` must mirror `tagged_teams`") belongs in the app's CLAUDE.md. The cross-cutting *mechanic* it leans on — manager selection, migration patterns, soft-delete semantics — is a `.claude/rules/` concern. Before writing a mechanic as a per-app fact, check it is not already a general rule: if it belongs in `rules/`, cite it or leave it out — never smuggle a cross-cutting standard into an app file as a one-off "exception".

---

## Authoring / Editing Workflow

1. **Read the current file** (if one exists) and count its lines. Note whether it is already over budget.
2. **Classify the request:**
   - *New file* → draft WHAT/WHY/HOW, then cut to the bone.
   - *Add a rule* → first check it isn't a linter's job (Rule 4), isn't already covered, and (Rule 7) verify any borrowed rationale is true and the fact isn't a cross-cutting `rules/` concern. If the file is large, find what to remove or move to an agent-doc to make room.
   - *Trim / improve* → hunt for: auto-generated boilerplate, style rules a linter owns, task-specific detail that should be a pointer, restated-the-obvious WHAT, duplicated instructions.
3. **Apply progressive disclosure:** anything detailed or area-specific becomes an agent-doc with a one-line pointer.
4. **Place high-stakes rules at the edges** (Rule 5).
5. **Report the line delta** — state the before/after line count and, for anything you moved out, where it now lives. Call out explicitly if the file is still over ~300 lines.

---

## Anti-Patterns to Flag (and fix)

- ❌ Pages of code-style rules a formatter already enforces.
- ❌ Pasted code snippets that will drift from source.
- ❌ Task-/module-specific guidance in the always-loaded file instead of a pointer.
- ❌ Auto-generated `/init` dump left unedited.
- ❌ "Be careful", "write clean code", "follow best practices" — non-actionable filler that spends budget and changes nothing.
- ❌ A *rationale* copied from a code comment/docstring without verifying it (Rule 7) — a wrong "why" in always-loaded memory misleads forever.
- ❌ A cross-cutting mechanic (manager choice, migration pattern) written as a per-app "exception" instead of living in `.claude/rules/`.
- ❌ A file creeping past 300 lines because every PR appended "one more rule" and none ever removed one.
