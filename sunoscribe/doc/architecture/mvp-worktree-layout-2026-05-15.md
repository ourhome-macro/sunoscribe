# MVP Worktree Layout Note (2026-05-15)

## Current Worktrees

Created worktrees:

```text
E:/project/sunoscribe/sunoscribe                      main
E:/project/sunoscribe/sunoscribe-candidate-authority  develop/candidate-authority
E:/project/sunoscribe/sunoscribe-artifact-revision    develop/artifact-revision
E:/project/sunoscribe/sunoscribe-job-runner           develop/job-runner
E:/project/sunoscribe/sunoscribe-fixture-gate         develop/fixture-gate
```

All four new worktrees currently point to:

```text
87c7b5e Refactor F0 to NoteCandidate pipeline and integrate new NoteCandidateBuilder
```

## Important Warning

The main working tree still has many uncommitted changes under `sunoscribe/...`.

Therefore the new worktrees do **not** include the latest uncommitted migration work such as:

- NoteCandidateSet v2 selection authority changes;
- quantizer lineage hard-fail changes;
- ScoreIR quantized primary input changes;
- current MVP documents/reviews.

If Codex starts coding in the new worktrees immediately, it will work from the older committed baseline and may redo or conflict with the current uncommitted work.

## Recommended Safe Path

Before assigning Codex tasks to the worktrees, create an integration commit or patch from the main worktree.

### Option A: Commit integration baseline

Use this if the current migration state is worth preserving as a shared base:

```powershell
cd E:\project\sunoscribe\sunoscribe
git add sunoscribe/backend sunoscribe/doc
git commit -m "WIP lead vocal MVP authority and lineage hardening"
```

Then rebase each worktree branch onto main:

```powershell
git -C E:\project\sunoscribe\sunoscribe-candidate-authority rebase main
git -C E:\project\sunoscribe\sunoscribe-artifact-revision rebase main
git -C E:\project\sunoscribe\sunoscribe-job-runner rebase main
git -C E:\project\sunoscribe\sunoscribe-fixture-gate rebase main
```

### Option B: Export a patch

Use this if the current migration state should not be committed yet:

```powershell
cd E:\project\sunoscribe\sunoscribe
git diff > ..\lead-vocal-mvp-current-wip.patch
git diff --cached > ..\lead-vocal-mvp-current-staged.patch
```

Then apply only the needed patch to the first worktree that should continue from that state.

## Suggested Assignment

### `develop/candidate-authority`

Use first.

Goal:

- move `ContourToCandidateBridge` to shadow diagnostics;
- remove production mutation of `detected_notes`;
- update tests so bridge no longer creates production lead notes;
- keep `NoteCandidateSet v2` as selector authority.

### `develop/artifact-revision`

Use after candidate authority stabilizes.

Goal:

- minimal artifact manifest or Artifact rows;
- immutable machine ScoreRevision;
- exports tied to revision.

### `develop/job-runner`

Use after artifact/revision shape is stable.

Goal:

- async job/status/failure persistence;
- background execution wrapper;
- status and artifact listing API/service hooks.

### `develop/fixture-gate`

Can prepare in parallel but should avoid production pipeline edits.

Goal:

- fixture config and runner;
- no large audio committed;
- no-vocal negative and lineage gates.

## Rule

One worktree, one branch, one Codex session, one bounded task.

Do not let multiple worktrees edit the same files unless one branch has already been merged or rebased.
