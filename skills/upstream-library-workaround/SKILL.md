---
name: upstream-library-workaround
description: "Handle buggy or wrong-behaving third-party library code when patching upstream is not an option — wrappers, monkeypatches, and vendoring, with the trade-offs of each."
tags: [dependencies, workaround, python, methodology]
---

# Upstream Library Workaround

Pattern for handling buggy or wrong-behaving third-party library code when you can't (or shouldn't) patch the upstream itself.

## When to use

- A library function/property returns wrong values in a specific scenario.
- The library is depended on by other code paths you don't want to break.
- Forking + patching the library is too heavy (you'd own a maintenance burden).
- You can identify the *underlying state* the property is supposed to compute from and replicate the correct logic locally.

If the library itself is unmaintained and you're the only consumer, fork it. This skill is for the more common case where the library is shared.

## Diagnosis

Before assuming the library is wrong, confirm:

1. **You're calling it correctly** — read the docs, check the version, check whether you're hitting a deprecated path.
2. **You can reproduce in isolation** — minimal repro outside your full pipeline.
3. **The underlying state is correct** — the bug is in the *derivation*, not in the input you're feeding.

If all three hold, the library is wrong (or wrong for your case) and the workaround is justified.

A common shape: a library exposes a high-level helper (e.g. `stats.threshold`) that internally branches based on flags (e.g. `clusters_defined`) and short-circuits to a fallback path that's wrong for your scenario. The underlying flag the helper *should* check (e.g. `use_auto_threshold`) is exposed separately. You can derive the correct value yourself.

## The workaround pattern

1. **Write a helper** named for the *behavior you want*, not the library it replaces:

   ```python
   def effective_threshold(stats):
       """Return the threshold actually in use, honoring manual override.

       PyQLB's stats.threshold short-circuits to single_auto_threshold
       when clusters_defined is True, dropping manual re-thresholds.
       """
       if stats.use_auto_threshold:
           return stats.single_auto_threshold
       return stats.manual_threshold
   ```

2. **Comment the *why*, not the *what*** — name the broken upstream path explicitly so a future reader understands why this helper exists. Without that, someone will delete it as duplication.

3. **Replace every call site** in the affected code path. Grep for the broken property and audit each hit — some may legitimately want the broken behavior (rare, but check).

4. **Remove orphan calls** — once the helper is in place, look for stray references to the broken property that aren't producing values you use. Delete them; they're dead weight that confuses future readers.

5. **Pin the bug with unit tests**:

   ```python
   def test_manual_threshold_honored_when_clusters_defined():
       stats = make_stats(use_auto_threshold=False, manual_threshold=3500, clusters_defined=True)
       assert effective_threshold(stats) == 3500
   ```

   Cover the original bug scenario plus the inverse (auto path still works) plus edge cases. These tests are the canary for an upstream fix later.

6. **Validate against real data** — run the helper on a real input file the user provided and confirm it produces sensible values (e.g. all wells return non-zero where the user re-thresholded). Unit tests prove correctness against your model; real data proves your model matches reality.

## When upstream eventually fixes it

- Your unit tests will still pass (your helper still returns the correct value).
- Run an A/B: replace one call site with the upstream property and check tests still pass.
- If upstream is fixed, you can remove the helper. Keep the unit tests — they now guard against future regressions in upstream.

## Anti-patterns

- **Patching at every call site inline** — duplicates logic, easy to miss one.
- **Monkey-patching the library** at import time — works but obscures behavior; future readers won't know why upstream behaves differently.
- **Catching the wrong value and substituting** (e.g. `if stats.threshold == 0: stats.threshold = manual`) — symptom-treating; misses cases where the wrong value happens to be non-zero.
- **Forking the library for a one-line fix** — maintenance burden out of proportion to the bug.
- **Skipping the unit test** because "it's just a workaround" — workarounds are exactly the code most likely to be touched later by someone who doesn't understand it.

## Naming

Name the helper after the domain concept (`effective_threshold`, `actual_user_id`, `resolved_path`), not the library it replaces (`fixed_threshold`, `pyqlb_threshold_v2`). The helper should read as if it had always been part of your codebase.

## Cross-references

- `vendor-format-round-trip-diff.md` — when the upstream library is producing wrong values *and* the format itself is wrong, separate the two issues.
- `user-driven-debugging.md` — when the user discovers the workaround manually first.
