
import pathlib
import statistics
import sys
import time

# Locate the compiler source folder.
PROJECT_DIR = (
    pathlib.Path(__file__).resolve().parent
    / "speculative_jit_prototype"
)

sys.path.insert(0, str(PROJECT_DIR))

from parser import Parser
from runtime import Runtime


# Simple workload supported by the prototype language.
SOURCE = """
fn double(x) {
    return x * 2;
}
print(double(10));
print(double(20));
print(double(30));
print(double(40));
print(double(50));
"""


def run_once(hot_threshold):
    """Create a fresh runtime and execute the workload."""
    program = Parser(SOURCE).parse()
    runtime = Runtime(
        program,
        hot_threshold=hot_threshold
    )

    start = time.perf_counter()
    output = runtime.run()
    elapsed = time.perf_counter() - start

    return elapsed, output, runtime.profile


def benchmark(hot_threshold, repetitions=7):
    """Warm up and measure repeated fresh-runtime executions."""
    for _ in range(2):
        run_once(hot_threshold)

    timings = []
    final_output = None
    final_profile = None

    for _ in range(repetitions):
        elapsed, output, profile = run_once(hot_threshold)
        timings.append(elapsed)
        final_output = output
        final_profile = profile

    return {
        "median_ms": statistics.median(timings) * 1000,
        "output": final_output,
        "profile": final_profile,
    }


def main():
    print("Speculative JIT Prototype Benchmark")
    print("Workload: five calls to double(x)")
    print("Measurement: median of 7 fresh-runtime runs")
    print()

    # A very high threshold prevents normal hot-tier promotion.
    baseline = benchmark(hot_threshold=10**9)

    # A low threshold encourages compilation after repeated calls.
    guarded = benchmark(hot_threshold=1)

    print("=== Interpreter-oriented configuration ===")
    print(f"Median runtime: {baseline['median_ms']:.4f} ms")
    print(f"Program output: {baseline['output']}")

    print()
    print("=== Low-threshold guarded configuration ===")
    print(f"Median runtime: {guarded['median_ms']:.4f} ms")
    print(f"Program output: {guarded['output']}")

    print()
    if baseline["output"] != guarded["output"]:
        print("ERROR: The two configurations produced different outputs.")
        raise SystemExit(1)

    baseline_ms = baseline["median_ms"]
    guarded_ms = guarded["median_ms"]

    if baseline_ms > 0:
        change = (guarded_ms / baseline_ms - 1) * 100
        print(f"Relative runtime change: {change:+.2f}%")
        print("Positive means the guarded configuration was slower.")
        print("Negative means the guarded configuration was faster.")

    print()
    print("Output consistency: PASS")
    print()
    print("Baseline runtime profile:")
    for name, stats in baseline["profile"].items():
        print(
            f"  {name}: calls={stats['calls']}, "
            f"compiles={stats['compile_count']}, "
            f"deopts={stats['deopts']}, "
            f"status={stats['jit_status']}"
        )

    print()
    print("Guarded runtime profile:")
    for name, stats in guarded["profile"].items():
        print(
            f"  {name}: calls={stats['calls']}, "
            f"compiles={stats['compile_count']}, "
            f"deopts={stats['deopts']}, "
            f"status={stats['jit_status']}"
        )


if __name__ == "__main__":
    main()
