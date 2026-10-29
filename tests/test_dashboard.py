import json
from io import BytesIO
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from dashboard import execute_source, compare_modes, Handler, BUILD_ID, probe_port


class DashboardTests(unittest.TestCase):
    def test_local_compile_run_and_ssa(self):
        result = execute_source({'source': 'fn f(x){let y=x+1; return y;} print(f(4));', 'optimize': True})
        self.assertEqual(result['output'], [5])
        self.assertIn('f', result['ssa'])
        self.assertEqual(len(result['stats']), 4)

    def test_source_limit_is_validated(self):
        with self.assertRaisesRegex(ValueError, '30 KB'):
            execute_source({'source': 'x' * 30001})

    def test_c_frontend_and_run_telemetry(self):
        source = '''#include <stdio.h>
int choose(int x) { if (x > 3) { return 10; } else { return 2; } }
int main(void) { printf("%d\\n", choose(5)); printf("%d\\n", choose(1)); return 0; }
'''
        result = execute_source({'source': source, 'c': True})
        self.assertEqual(result['output'], [10, 2])
        self.assertIn('C', result['telemetry']['frontend'])
        self.assertGreaterEqual(result['telemetry']['total_ms'], 0)
        for mode in ('baseline', 'optimized', 'guarded'):
            compared = execute_source({'source': source, 'c': True, 'mode': mode})
            self.assertEqual(compared['output'], [10, 2], mode)
            self.assertEqual(compared['telemetry']['mode'], mode)
        self.assertTrue(compare_modes({'source': source, 'c': True})['equivalent'])

    def test_c_for_loop_sample_preserves_result_in_all_optimization_modes(self):
        source = '''#include <stdio.h>

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
        results = [execute_source({'source': source, 'c': True, 'mode': mode}) for mode in ('baseline', 'optimized', 'guarded')]
        self.assertEqual([row['output'] for row in results], [[110], [110], [110]])
        comp = compare_modes({'source': source, 'c': True})
        self.assertTrue(comp['equivalent'])
        self.assertEqual(comp['modes']['baseline']['output'], [110])
        self.assertEqual(comp['modes']['optimized']['output'], [110])
        self.assertEqual(comp['modes']['guarded']['output'], [110])

    def test_auto_detection_of_c_and_sjit(self):
        c_src = '#include <stdio.h>\nint main(void){ printf("%d\\n", 42); return 0; }'
        res_c = execute_source({'source': c_src})
        self.assertEqual(res_c['output'], [42])
        self.assertIn('C', res_c['telemetry']['frontend'])

        sjit_src = 'fn answer(){ return 42; } print(answer());'
        res_sjit = execute_source({'source': sjit_src})
        self.assertEqual(res_sjit['output'], [42])
        self.assertEqual(res_sjit['telemetry']['frontend'], '.sjit')

    def test_compare_reports_each_frontend_or_runtime_error(self):
        comparison = compare_modes({'source': 'not valid source !!!'})
        self.assertFalse(comparison['equivalent'])
        self.assertEqual(set(comparison['modes']), {'baseline', 'optimized', 'guarded'})
        self.assertTrue(all('error' in row for row in comparison['modes'].values()))

    def test_run_endpoint_streams_runtime_events_and_final_result(self):
        class FakeHandler:
            def __init__(self):
                self.wfile = BytesIO()
                self.close_connection = False
                self.headers_sent = []

            def send_response(self, status):
                self.status = status

            def send_header(self, key, value):
                self.headers_sent.append((key, value))

            def end_headers(self):
                pass

        handler = FakeHandler()
        Handler.stream_run(handler, {'source': 'fn inc(x){return x+1;} print(inc(3));', 'mode': 'guarded'})
        lines = [json.loads(line) for line in handler.wfile.getvalue().decode().splitlines()]
        self.assertEqual(handler.status, 200)
        self.assertIn(('Content-Type', 'application/x-ndjson; charset=utf-8'), handler.headers_sent)
        self.assertTrue(handler.close_connection)
        self.assertEqual(lines[0]['type'], 'status')
        self.assertTrue(any(row.get('type') == 'event' and row['event'].startswith('JIT inc:') for row in lines))
        self.assertEqual(lines[-1]['type'], 'result')
        self.assertEqual(lines[-1]['result']['output'], [4])

    def test_probe_port_on_unused_port(self):
        # Probing an unused high port returns free or occupied
        state = probe_port(59123)
        self.assertIn(state['state'], ('free', 'occupied'))

    def test_dashboard_html_dom_integrity(self):
        html_path = pathlib.Path(__file__).resolve().parents[1] / 'dashboard.html'
        content = html_path.read_text(encoding='utf-8')
        # Ensure critical elements exist
        self.assertIn('id="ssaPre"', content)
        self.assertIn('id="tabCFGDiagram"', content)
        self.assertIn('id="visualCFGContainer"', content)
        self.assertIn('id="runTelemetryGrid"', content)
        self.assertIn('id="outputPre"', content)
        self.assertIn('id="btnRun"', content)
        self.assertIn('id="btnCompare"', content)
        # Ensure ssaPre is not nested inside tabCFGDiagram so diagram updates do not destroy it
        self.assertNotIn('<div id="tabCFGDiagram"><pre id="ssaPre">', content.replace(' ', '').replace('\n', ''))
        # Ensure renderFunctionCFG updates tabCFGDiagram and visualCFGContainer
        self.assertIn("q('#visualCFGContainer')", content)
        self.assertIn("q('#tabCFGDiagram')", content)
        self.assertNotIn("q('#tabCFGContainer')", content)

        # Ensure animated pipeline elements and controls exist
        self.assertIn('id="pipelineCard"', content)
        self.assertIn('id="btnSimulatePipeline"', content)
        self.assertIn('id="btnSimulateDeopt"', content)
        self.assertIn('id="btnToggleAscii"', content)
        self.assertIn('id="pipelineLiveTelemetry"', content)
        self.assertIn('id="animatedPipeline"', content)
        self.assertIn('id="stage-frontend"', content)
        self.assertIn('id="stage-ast"', content)
        self.assertIn('id="stage-ssa"', content)
        self.assertIn('id="stage-profiler"', content)
        self.assertIn('id="stage-guarded"', content)
        self.assertIn('id="stage-deopt"', content)
        self.assertIn('id="stageInspector"', content)

        # Ensure enhanced test suite & demo explorer elements exist
        self.assertIn('id="btnRunTests"', content)
        self.assertIn('id="testCardsList"', content)
        self.assertIn('id="testSummaryContainer"', content)
        self.assertIn('id="testProgressFill"', content)
        self.assertIn('id="testFilterRow"', content)
        self.assertIn('id="testOutputPre"', content)
        self.assertIn('id="demoShowcaseCard"', content)
        self.assertIn('id="demoCodePreview"', content)
        self.assertIn('id="demoShowcaseTitle"', content)
        self.assertIn('id="demoTelemetryRow"', content)
        self.assertIn('id="demoOutputPre"', content)

        # Ensure enhanced runtime telemetry & deopts elements exist
        self.assertIn('id="profileCard"', content)
        self.assertIn('id="eventsCard"', content)
        self.assertIn('id="profileFunctionCards"', content)
        self.assertIn('id="runtimeProfileSummary"', content)
        self.assertIn('id="runtimeEventsTimeline"', content)
        self.assertIn('id="eventFilterRow"', content)
        self.assertIn('id="timingStackedBar"', content)
        self.assertIn('id="segParse"', content)
        self.assertIn('id="segExec"', content)
        self.assertIn('id="profilePre"', content)
        self.assertIn('id="runtimeEventsPre"', content)
        self.assertIn('id="fullTelemetryGrid"', content)
        self.assertIn(f"EXPECTED_BUILD = '{BUILD_ID}'", content)


if __name__ == '__main__':
    unittest.main()
