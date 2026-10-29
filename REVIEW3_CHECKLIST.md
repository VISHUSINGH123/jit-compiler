# Review 3 sprint checklist

## Completed in this sprint
- [x] Preserve the Review 2 `.sjit` language and runtime.
- [x] Add a `pycparser`-based C-subset frontend.
- [x] Translate supported C constructs into the existing AST.
- [x] Add explicit CFG block objects and edges for `if` and `while`.
- [x] Add AST-level constant folding/propagation and constant-branch simplification.
- [x] Add C examples for arithmetic, branches and loops.
- [x] Add tests for C input, CFG edges, optimizer and legacy behaviour.
- [x] Add repeatable 30-run smoke benchmark with output equivalence check.
- [x] Add dominance/frontier analysis, branch/loop phis, renaming and SSA verification.
- [x] Add ordered constant, copy, CSE and conservative dead-store passes with SSA snapshots.
- [x] Add guarded Python bytecode plans and observed-signature recompilation.
- [x] Add five-family cold/warm benchmark and local dashboard.
- [x] Document what is and is not implemented.

## Remaining limitations
- [ ] Execute explicit SSA IR rather than AST/Python bytecode plans.
- [ ] Move optimizations onto executable SSA; add LICM only with a correct safety/effects model.
- [ ] Add broader C semantic checks and supported types.
- [ ] Add precise mid-function deoptimization state maps.
- [ ] Native machine-code backend remains unimplemented.

## 3–5 minute demo script
1. `python main.py examples/arithmetic.c --show-ir --dump-cfg`
2. Explain that the C subset is translated into the prototype's AST and show output `42`.
3. `python main.py examples/loop.c --dump-cfg` and explain the supported `for`-to-`while` lowering.
4. `python main.py examples/demo.sjit --show-ir` to show hot-function promotion.
5. `python main.py examples/deopt_demo.sjit --hot-threshold 1` to show a type guard failure and interpreter restart.
6. `python -m unittest discover -s tests -v`
7. `python benchmarks/run_benchmarks.py`; explain that unstable inputs may be slower and this is not native JIT.
8. `python dashboard.py`, then open `http://127.0.0.1:8765`.

## Honest report wording
"Review 3 adds verified scalar SSA construction, conservative AST optimization, adaptive guarded Python bytecode plans, entry-restart deoptimization, multi-workload measurements, and a local dashboard. SSA execution, precise mid-function recovery, full C semantics, and native machine-code generation remain future work."
