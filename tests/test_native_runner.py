import pathlib
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from native_runner import native_compare, find_compiler


class NativeRunnerTests(unittest.TestCase):
    @patch('native_runner.find_compiler', return_value=None)
    def test_unavailable_compiler_is_reported_without_fake_results(self, _find):
        result = native_compare('int main(void) { return 0; }', 'c')
        self.assertFalse(result['available'])
        self.assertIn('visible to this dashboard', result['error'])

    @patch('native_runner.find_compiler', return_value=('msvc', r'C:\BuildTools\cl.exe'))
    @patch('native_runner.subprocess.run')
    def test_msvc_baseline_and_optimized_output_and_timings(self, run, _find):
        def fake_run(command, **kwargs):
            output = next((arg[4:] for arg in command if arg.startswith('/Fe:')), None)
            if output:
                pathlib.Path(output).write_bytes(b'fake exe')
                return subprocess.CompletedProcess(command, 0, b'', b'Microsoft (R) C/C++ Optimizing Compiler Version 19.51\nMSVC compile ok')
            return subprocess.CompletedProcess(command, 0, b'110\r\n', b'')

        run.side_effect = fake_run
        source = '''#include <stdio.h>
int calculate(int n) { int total=0; for (int i=1; i<=n; i++) { total=total+i*2; } return total; }
int main(void) { printf("%d\\n", calculate(10)); return 0; }
'''
        result = native_compare(source, 'c')
        self.assertTrue(result['available'])
        self.assertTrue(result['equivalent'])
        self.assertEqual(len(result['modes']['native-baseline']['runtime_trials_ms']), 5)
        self.assertGreaterEqual(result['modes']['native-optimized']['compile_ms'], 0)
        commands = [call.args[0] for call in run.call_args_list if any(arg.startswith('/Fe:') for arg in call.args[0])]
        self.assertIn('/Od', commands[0])
        self.assertIn('/O2', commands[1])

    def test_rejects_unknown_language(self):
        with self.assertRaisesRegex(ValueError, r'C or C\+\+'):
            native_compare('int main() { return 0; }', 'rust')

    def test_sjit_input_gets_actionable_native_compiler_message(self):
        result = native_compare('fn sum(n){return n+1;} print(sum(3));', 'c')
        self.assertFalse(result['available'])
        self.assertIn('project .sjit language', result['error'])
        self.assertIn('Run selected mode', result['error'])

    def test_real_msvc_if_detected(self):
        compiler = find_compiler('c')
        if compiler and compiler[0] == 'msvc':
            source = '''#include <stdio.h>
int main(void) { printf("%d\\n", 110); return 0; }
'''
            res = native_compare(source, 'c')
            if res.get('available'):
                self.assertEqual(res['compiler_family'], 'msvc')
                base_mode = res['modes']['native-baseline']
                if not base_mode.get('error'):
                    self.assertEqual(base_mode['exit_code'], 0)
                    self.assertIn('110', base_mode['stdout'])


if __name__ == '__main__':
    unittest.main()
