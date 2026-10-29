# Profile-Guided Speculative JIT Compiler & Interactive Suite

A high-performance prototype for **A Profile-Guided Speculative JIT Compiler with Runtime-Adaptive SSA Optimization, Guarded Bytecode Tier, and Native MSVC Comparison**.

---

## Windows Quickstart & Dashboard Launch

### 1. Launch Command
Open the VS Code terminal (or Developer Command Prompt / PowerShell) and run:

```powershell
python "M:\projects\comp project\review3_compiler_sprint\dashboard.py"
```

The server automatically:
- Scans candidate ports (`8765`, `8766`, `8767`, `8787`, `8000`, `8080`), detecting and warning about stale dashboard instances.
- Detects your local Visual Studio MSVC C/C++ toolchain (`cl.exe`), auto-configuring environment paths via `vswhere` / `vcvarsall.bat` if `cl` is not yet on `PATH`.
- Prints the exact URL in the console (e.g. `http://127.0.0.1:8765`).
- Opens your default web browser to the dashboard.
- Sends anti-caching HTTP headers so browser refreshes always match the latest running build.

To bind to an explicit port if needed:
```powershell
python "M:\projects\comp project\review3_compiler_sprint\dashboard.py" --port 8765
```

### 2. Stopping Stale Instances
If an old dashboard instance holds a port, the startup console prints its PID. Terminate it in PowerShell:
```powershell
Stop-Process -Id <PID> -Force
```

---

## Dashboard Usage & Interface Guide

The web dashboard is vibrant, color-coded, and organized into 7 interactive tabs:

### 1. Source Editor & Comparison Panels
- **Language Mode Badges:**
  - `Amber Pill:` **Project .sjit DSL** (Handwritten lexer/parser, verified SSA, Python bytecode execution plan).
  - `Emerald Pill:` **C Teaching Subset** (pycparser AST, verified SSA, Python bytecode plan + Native MSVC compilation).
  - `Violet Pill:` **C++** (Supported via Native MSVC /Clang/GCC compiler panel).
- **Project Modes Comparison:**
  - Compares **Baseline Interpreter**, **Optimized Interpreter**, and **Guarded Speculative Tier**.
  - Displays output equivalence badge (`✓ ALL OUTPUTS EQUIVALENT`).
  - Comparative execution timing chart.
- **Native MSVC Compiler Panel:**
  - Compares MSVC `/Od` (debug/baseline) and `/O2` (release/optimized).
  - Displays compiler identity (e.g. `Microsoft (R) C/C++ Optimizing Compiler Version 19.51.36260 for x64`), compiler path, binary size, compilation time, warm-up run, and median of 5 repeated runtime trials.
  - **Notice on .sjit Code:** If `.sjit` syntax (`fn`, `let`, `print`) is entered, the panel cleanly guides you to use the Project buttons above rather than passing invalid syntax to MSVC.

### 2. Regression Test Sample
Load sample **`C For Loop (Regression)`** in the editor:
```c
#include <stdio.h>

int calculate(int n) {
    int total = 0;
    for (int i = 1; i <= n; i++) {
        total = total + i * 2;
    }
    return total;
}

int main(void) {
    printf("%d\n", calculate(10));
    return 0;
}
```
- **Project Baseline:** `[110]`
- **Project Optimized:** `[110]`
- **Project Guarded:** `[110]`
- **Native MSVC `/Od`:** `110`
- **Native MSVC `/O2`:** `110`
- **Cross-Engine Equivalence:** `True`

### 3. Timing Boundaries & Honest Labels
- **Native Timings:** Median whole-process execution time (process creation, C runtime init, `main()`, exit) across 5 trials following an untimed warm-up run.
- **Project Timings:** In-process Python AST execution stage time inside the running dashboard.
- *These are separate timing boundaries and are honestly labeled in all charts and telemetry cards.*

### 4. Completed-Run Event Trace
- During streaming execution: Displays live pulsing badge `● Streaming runtime events...`.
- Upon completion: Labeled as `Completed-Run Event Trace (Chronological)` with color-coded badges for `JIT`, `DEOPT`, `POLICY`, `RECOMPILE`, and `OPT`.

---

## Command-Line Verification & Testing

### Run Test Suite (34 Unittests)
```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

### Run Benchmark Suite (5 Workloads, Medians)
```powershell
python benchmarks/run_benchmarks.py
```

### Run Prototype Micro-Benchmark
```powershell
python bench.py
```

---

## Seven-Module Architecture Mapping

1. **Lexical Analyzer:** `lexer.py` (tokenization of `.sjit`)
2. **Parser:** `parser.py` (recursive descent & Pratt expression parser) and `c_frontend.py` (pycparser C teaching subset)
3. **AST-to-SSA Lowering:** `cfg.py` and `ssa.py` (explicit CFG, dominators, dominance frontiers, Cytron phi placement, renaming, verifier)
4. **Interpreter with Profiling:** `runtime.py` (call counts, type signatures, branch and loop counters)
5. **JIT Execution Plan Tier:** `py_executor.py` and `runtime.py` (guarded Python bytecode plans, not native machine code)
6. **Deoptimization Framework:** `runtime.py` (entry-argument snapshot and interpreter restart upon type guard mismatch)
7. **Feedback-Driven Recompilation Controller:** `runtime.py` (failed-signature tracking, deopt budget, adaptive recompilation)

---

## Limitations & Scope

1. **Native Compiler vs Project Executor:** Native compilation invokes the installed system compiler (MSVC `cl.exe`) to compare `/Od` and `/O2`. The project speculative JIT tier executes Python bytecode plans (`py_executor.py`); it does not emit machine code.
2. **C Language Scope:** The project frontend supports a small teaching subset of C (scalar variables, `if`/`else`, `while`, `for`, named functions, direct calls, integer `printf`). C++ and arbitrary system headers are compiled through the native compiler panel.
3. **Optimizer Scope:** Passes (`optimizer.py`) operate conservatively over the AST. Loop variables and condition aliases are strictly protected across loop boundaries to ensure loop termination.
