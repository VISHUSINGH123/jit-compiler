
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from parser import Parser
from runtime import Runtime


class JITTierTests(unittest.TestCase):

    def test_hot_function_compiled(self):
        src = """
        fn twice(x) { return x * 2; }
        print(twice(10));
        print(twice(10));
        print(twice(10));
        print(twice(10));
        print(twice(10));
        """
        runtime = Runtime(Parser(src).parse(), hot_threshold=3)

        self.assertEqual(runtime.run(), [20, 20, 20, 20, 20])
        self.assertEqual(runtime.profile["twice"]["compile_count"], 1)
        self.assertEqual(runtime.profile["twice"]["deopts"], 0)

    def test_guard_failure_recovers(self):
        src = """
        fn increment(x) { return x + 1; }
        fn main() {
            let first = increment(7);
            let second = increment(true);
            return first + second;
        }
        print(main());
        """
        runtime = Runtime(Parser(src).parse(), hot_threshold=1)

        self.assertEqual(runtime.run(), [10])
        self.assertEqual(runtime.profile["increment"]["deopts"], 1)
        self.assertTrue(
            any(event.startswith("DEOPT increment:")
                for event in runtime.events)
        )
        deopt=next(event for event in runtime.events if event.startswith('DEOPT increment:'))
        self.assertIn('stage=compiled-entry-type-guard',deopt)
        self.assertIn('restart-in-interpreter-at-function-entry',deopt)

    def test_budget_exhaustion(self):
        src = """
        fn increment(x) { return x + 1; }
        fn main() {
            let first = increment(7);
            let second = increment(true);
            return first + second;
        }
        print(main());
        """
        runtime = Runtime(
            Parser(src).parse(),
            hot_threshold=1,
            deopt_budget=1
        )

        self.assertEqual(runtime.run(), [10])
        self.assertNotIn("increment", runtime.code_cache)
        self.assertIn(
            "interpreter-only (deopt budget exhausted)",
            runtime.profile["increment"]["jit_status"]
        )
        self.assertTrue(
            any(event.startswith("POLICY increment:")
                for event in runtime.events)
        )

    def test_guard_failure_recompiles_observed_signature(self):
        src = 'fn inc(x){return x+1;} print(inc(3)); print(inc(true)); print(inc(true));'
        runtime=Runtime(Parser(src).parse(),hot_threshold=1,deopt_budget=3)
        self.assertEqual(runtime.run(),[4,2,2])
        self.assertEqual(runtime.profile['inc']['deopts'],1)
        self.assertEqual(runtime.profile['inc']['compile_count'],2)
        self.assertTrue(any(e.startswith('RECOMPILE inc:') for e in runtime.events))
        self.assertTrue(any('stage=post-recovery' in e for e in runtime.events))

    def test_unsupported_undefined_read_falls_back_with_runtime_fault(self):
        from runtime import RuntimeFault
        runtime=Runtime(Parser('fn bad(){return missing;} print(bad());').parse(),hot_threshold=1)
        with self.assertRaises(RuntimeFault):runtime.run()


if __name__ == "__main__":
    unittest.main()
