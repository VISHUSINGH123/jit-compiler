import argparse
from pathlib import Path
from lexer import Lexer
from parser import Parser
from ir import IRPrinter
from runtime import Runtime
from c_frontend import CFrontend, CFrontendError
from optimizer import PassManager
from cfg import CFG
from ssa import build_ssa

def main():
    ap = argparse.ArgumentParser(description="Profile-guided speculative JIT compiler prototype")
    ap.add_argument("file", help="path to .sjit or supported-subset .c source")
    ap.add_argument("--hot-threshold", type=int, default=3)
    ap.add_argument("--deopt-budget", type=int, default=2)
    ap.add_argument("--show-tokens", action="store_true")
    ap.add_argument("--show-ir", action="store_true")
    ap.add_argument("--dump-cfg", action="store_true")
    ap.add_argument("--optimize", action="store_true", help="run AST-level constant folding/propagation and branch simplification")
    args = ap.parse_args()
    path = Path(args.file)
    source = path.read_text(encoding="utf-8")
    try:
        if path.suffix.lower() == ".c":
            program = CFrontend().parse(source)
            print("Frontend: C subset (pycparser); see README for supported constructs.")
        else:
            if args.show_tokens:
                print("=== Tokens ===")
                for t in Lexer(source).tokenize(): print(t)
            program = Parser(source).parse()
        if args.optimize:
            manager=PassManager()
            program=manager.run(program)
            print("=== Optimization pass statistics ===")
            for stat in manager.stats:print(f"{stat['pass']}: changed={stat['changed']} ({stat['before_chars']} -> {stat['after_chars']} chars)")
            if args.show_ir:
                for snap in manager.dumps:
                    print(f"--- {snap['pass']} before ---\n{snap['before']}\n--- {snap['pass']} after ---\n{snap['after']}")
        if args.dump_cfg:
            print("=== CFG ===")
            all_blocks = []
            for name, fn in program.functions.items():
                print(f"Function {name}:")
                print(CFG.from_statements(fn.body).dump())
        if args.show_ir:
            print("=== Verified SSA IR ===")
            for name, fn in program.functions.items():
                print(f"function @{name}({', '.join(fn.params)})")
                print(build_ssa(fn.body, fn.params).dump())
            if program.statements:
                print("function @<top-level>")
                print(build_ssa(program.statements).dump())
        runtime = Runtime(program, args.hot_threshold, args.deopt_budget)
        output = runtime.run()
        # C frontend invokes main once at top level. Keep existing warm-up demo behavior
        # for .sjit files that define main but do not print a result at top level.
        if path.suffix.lower() != ".c" and "main" in program.functions and not output:
            for _ in range(args.hot_threshold + 1):
                runtime.call("main", [])
        print("=== Program Output ===")
        for value in output: print(value)
        print("\n" + runtime.report())
    except (CFrontendError, Exception) as exc:
        ap.exit(2, f"Compilation/execution failed: {exc}\\n")

if __name__ == "__main__":
    main()
