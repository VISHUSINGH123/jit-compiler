import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from c_frontend import CFrontend
from runtime import Runtime
from optimizer import optimize_program, PassManager, cse_program, copy_program, dce_program
from parser import Parser, Number
from cfg import CFG
from ssa import build_ssa, verify_ssa

class Review3Tests(unittest.TestCase):
    def run_c(self, source, optimize=False):
        program = CFrontend().parse(source)
        if optimize:
            program = optimize_program(program)
        return Runtime(program).run()

    def test_c_arithmetic_and_printf(self):
        src = 'int twice(int x){ return x*2; } int main(void){ printf("%d\\\\n", twice(6)); return 0; }'
        self.assertEqual(self.run_c(src), [12])

    def test_c_for_loop(self):
        src = 'int main(){ int s=0; for(int i=0; i<5; i++){ s=s+i; } printf("%d", s); return 0; }'
        self.assertEqual(self.run_c(src), [10])

    def test_optimizer_folds_and_propagates(self):
        src = 'fn main(){ let x = 2 + 3; let y = x * 4; return y; } print(main());'
        p = optimize_program(Parser(src).parse())
        self.assertEqual(Runtime(p).run(), [20])
        body = p.functions['main'].body
        self.assertIsInstance(body[0].expr, Number)
        self.assertEqual(body[0].expr.value, 5)
        self.assertEqual(body[1].expr.value, 20)

    def test_cfg_has_explicit_edges(self):
        src = 'fn f(x){ if (x > 0) { return 1; } else { return 0; } }'
        p = Parser(src).parse()
        cfg = CFG.from_statements(p.functions['f'].body)
        self.assertGreaterEqual(len(cfg.blocks), 4)
        self.assertTrue(cfg.entry.successors)

    def test_ssa_phi_for_branch_and_loop(self):
        p = Parser('fn f(n){ let x=0; let i=0; while(i<n){ if(i>2){x=x+2;}else{x=x+1;} i=i+1; } return x; }').parse()
        ir = build_ssa(p.functions['f'].body, p.functions['f'].params)
        self.assertTrue(verify_ssa(ir))
        dump = ir.dump()
        self.assertIn('phi(', dump)
        self.assertIn('i.', dump)

    def test_ssa_verifier_rejects_bad_phi(self):
        p = Parser('fn f(x){ let y=0; if(x>0){y=1;}else{y=2;} return y; }').parse()
        ir = build_ssa(p.functions['f'].body, p.functions['f'].params)
        phi = next(phi for entries in ir.phis.values() for phi in entries)
        phi.incoming.pop(next(iter(phi.incoming)))
        with self.assertRaisesRegex(ValueError, 'phi predecessors'):
            verify_ssa(ir)

    def test_pass_manager_records_snapshots(self):
        manager = PassManager()
        result = manager.run(Parser('print(2+3);').parse())
        self.assertEqual(len(manager.dumps), 4)
        self.assertEqual(len(manager.stats), 4)
        self.assertEqual(Runtime(result).run(), [5])

    def test_copy_cse_and_dce_preserve_results(self):
        src='fn f(a){ let x=a+2; let y=a+2; let z=y; let dead=91; return z; } print(f(7));'
        original=Parser(src).parse(); optimized=dce_program(copy_program(cse_program(original)))
        self.assertEqual(Runtime(original).run(),Runtime(optimized).run())
        self.assertLess(len(repr(optimized)),len(repr(original)))

    def test_dce_keeps_stores_across_control_flow(self):
        src='fn f(c){let x=0; if(c){x=9;} return x;} print(f(true)); print(f(false));'
        p=Parser(src).parse()
        self.assertEqual(Runtime(p).run(),Runtime(dce_program(p)).run())

    def test_existing_language_runs_after_optimization(self):
        src = 'fn square(x){ return x*x; } print(square(7));'
        self.assertEqual(Runtime(optimize_program(Parser(src).parse())).run(), [49])

    def test_c_for_loop_calculate_regression_preserves_110(self):
        src = '''#include <stdio.h>

int calculate(int n) {
    int total = 0;
    for (int i = 1; i <= n; i++) {
        total = total + i * 2;
    }
    return total;
}

int main(void) {
    printf("%d\\n", calculate(10));
    return 0;
}
'''
        # Baseline
        prog = CFrontend().parse(src)
        self.assertEqual(Runtime(prog).run(), [110])

        # All AST passes
        manager = PassManager()
        opt_prog = manager.run(prog)
        self.assertEqual(Runtime(opt_prog).run(), [110])

        # Guarded speculative runtime
        self.assertEqual(Runtime(opt_prog, hot_threshold=1).run(), [110])

    def test_while_loop_with_pre_loop_alias_does_not_loop_infinitely(self):
        src = '''fn count(n){
            let a = 0;
            let i = a;
            let total = 0;
            while (i < n) {
                total = total + 1;
                i = i + 1;
            }
            return total;
        }
        print(count(5));'''
        prog = Parser(src).parse()
        opt = copy_program(prog)
        self.assertEqual(Runtime(opt).run(), [5])

if __name__ == '__main__':
    unittest.main()
