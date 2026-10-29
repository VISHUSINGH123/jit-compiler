# Review 3 report-to-prototype mapping

| Report requirement | Current status | Honest limitation |
|---|---|---|
| Handwritten lexer | Implemented for `.sjit` | Small language subset |
| Recursive-descent parser and AST | Implemented for `.sjit` | No full semantic type system |
| C frontend | Added using `pycparser` | Subset only; no full preprocessor or full C semantics |
| CFG/basic blocks | Explicit blocks/edges, iterative dominators/frontiers | Structured scalar language |
| SSA/phi functions | Cytron placement, renaming, verifier | Inspectable, not executable; `.undef` allowed |
| Optimizations | Constant, copy, pure CSE, conservative dead-store passes | AST-level; DCE skips control flow; no LICM |
| Interpreter with profiling | AST runtime with call/type/branch/loop feedback | Compiled plans skip branch/loop counters |
| Hot-function detection | Implemented | Configurable threshold |
| Speculative JIT | Guarded cached Python bytecode plan | No native machine code |
| Type guards | Function-entry argument-type guards | No interior guards |
| Deoptimization | Entry snapshot and restart in interpreter | Not arbitrary mid-function state reconstruction |
| Adaptive policy | Recompile to observed signature until budget | Call-entry restart only |
| Benchmark | Five workload classes, cold/warm medians, output checks | Small illustrative workloads; unstable types are slower |
| Dashboard | Local UI for code, SSA, passes, runtime, benchmark and tests | Launch with `python dashboard.py` |
| Under-15% profiling overhead | Not claimed | Needs a dedicated, comparable experiment |

## Review demo sequence

1. `python main.py examples/arithmetic.c --show-ir --dump-cfg`
2. `python main.py examples/loop.c --dump-cfg`
3. `python main.py examples/deopt_demo.sjit --hot-threshold 1`
4. `python -m unittest discover -s tests -v`
5. `python benchmarks/run_benchmarks.py`

## Remaining milestones

1. Execute verified SSA IR rather than the AST/Python bytecode plan.
2. Add SSA optimizer passes and safe LICM after an effect model exists.
3. Improve C semantic checking and supported types.
4. Add precise mid-function deoptimization state maps.
