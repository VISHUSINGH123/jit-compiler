"""Local-only Review 3 compiler dashboard. Run: python dashboard.py"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json, os, re, subprocess, sys, time
import threading, webbrowser
import socket
from http.client import HTTPConnection
from parser import Parser
from c_frontend import CFrontend
from runtime import Runtime
from optimizer import PassManager, optimize_program, copy_program, cse_program, dce_program
from ssa import build_ssa
from native_runner import compiler_status

ROOT = Path(__file__).resolve().parent
BUILD_ID = 'review3-20261029-dashboard-v5'
PREFERRED_PORTS = (8765, 8766, 8767, 8787, 8000, 8080)

SAMPLES = {
    'Loop': 'fn sum(n){let i=0; let s=0; while(i<n){s=s+i; i=i+1;} return s;} print(sum(20));',
    'Branches': 'fn choose(x){let y=0; if(x>3){y=10;}else{y=2;} return y;} print(choose(5)); print(choose(1));',
    'C Branches': '#include <stdio.h>\nint choose(int x) { if (x > 3) { return 10; } else { return 2; } }\nint main(void) { printf("%d\\n", choose(5)); printf("%d\\n", choose(1)); return 0; }',
    'C For Loop (Regression)': '#include <stdio.h>\n\nint calculate(int n) {\n    int total = 0;\n    for (int i = 1; i <= n; i++) {\n        total = total + i * 2;\n    }\n    return total;\n}\n\nint main(void) {\n    printf("%d\\n", calculate(10));\n    return 0;\n}',
    'Optimization': 'fn calc(){let x=2+3; let y=x*4; let unused=99; return y;} print(calc());',
    'Deoptimization': 'fn inc(x){return x+1;} fn main(){let a=inc(7); let b=inc(true); return a+b;} print(main());'
}

def jsonable(value):
    if isinstance(value, (set, tuple)):
        return list(value)
    if hasattr(value, 'items'):
        return {str(k): jsonable(v) for k, v in value.items()}
    return value

def profile_data(rt):
    return {
        n: {**{k: jsonable(v) for k, v in p.items()}, 'compiled_calls': rt.compiled_calls[n]}
        for n, p in rt.profile.items()
    }

def detect_is_c(source: str, hint=None) -> bool:
    if hint is True:
        # If user explicitly marked as C, verify it doesn't look purely like .sjit
        if re.search(r'^\s*fn\s+[A-Za-z_]', source, re.M):
            return False
        return True
    if hint is False:
        if '#include' in source or re.search(r'\bint\s+main\s*\(', source):
            return True
        return False
    # Auto-detection
    if '#include' in source or re.search(r'\bint\s+main\s*\(', source):
        return True
    return False

def execute_source(data, event_callback=None):
    started = time.perf_counter()
    source = data.get('source', '')
    if not isinstance(source, str) or not source.strip() or len(source) > 30000:
        raise ValueError('Enter source code under 30 KB')

    mode = data.get('mode')
    if mode not in (None, 'baseline', 'optimized', 'guarded'):
        raise ValueError('Unknown execution mode')
    do_optimize = (mode in ('optimized', 'guarded')) if mode else bool(data.get('optimize'))
    do_speculate = (mode == 'guarded') if mode else bool(data.get('speculate'))

    is_c = detect_is_c(source, data.get('c'))

    stage = time.perf_counter()
    program = CFrontend().parse(source) if is_c else Parser(source).parse()
    parse_ms = (time.perf_counter() - stage) * 1000

    choices = {
        'constant-fold/propagate': optimize_program,
        'copy-propagation': copy_program,
        'common-subexpression-elimination': cse_program,
        'dead-code-elimination': dce_program
    }
    selected = data.get('passes')
    manager = PassManager([(n, fn) for n, fn in choices.items() if selected is None or n in selected])

    stage = time.perf_counter()
    if do_optimize:
        program = manager.run(program)
    optimize_ms = (time.perf_counter() - stage) * 1000

    stage = time.perf_counter()
    ir = {}
    ssa_graphs = {}
    for n, f in program.functions.items():
        fn_ssa = build_ssa(f.body, f.params)
        ir[n] = fn_ssa.dump()
        blocks_data = []
        for b in fn_ssa.cfg.blocks:
            phis_data = [
                {'result': p.result, 'name': p.name, 'incoming': p.incoming}
                for p in fn_ssa.phis.get(b.name, [])
            ]
            ins_data = [
                {'op': i.op, 'result': i.result, 'value': repr(i.value)}
                for i in fn_ssa.instructions.get(b.name, [])
            ]
            blocks_data.append({
                'name': b.name,
                'preds': list(b.predecessors),
                'succs': list(b.successors),
                'dom': sorted(fn_ssa.dominators.get(b.name, set())),
                'frontier': sorted(fn_ssa.frontier.get(b.name, set())),
                'phis': phis_data,
                'instructions': ins_data
            })
        ssa_graphs[n] = {
            'function': n,
            'params': list(f.params),
            'blocks': blocks_data
        }
    ir_ms = (time.perf_counter() - stage) * 1000

    threshold = 1 if do_speculate else (10**9 if mode in ('baseline', 'optimized') else 3)
    rt = Runtime(program, hot_threshold=threshold, event_callback=event_callback)

    stage = time.perf_counter()
    rt.run()
    if not rt.output and 'main' in program.functions:
        for _ in range(3):
            rt.call('main', [])
    raw_execute_ms = (time.perf_counter() - stage) * 1000

    jit_compile_ms = sum(p.get('compile_ns', 0) for p in rt.profile.values()) / 1e6

    warm_exec_ms = None
    if do_speculate and rt.code_cache and 'main' in program.functions:
        saved_output = list(rt.output)
        t_warm = time.perf_counter()
        rt.call('main', [])
        warm_exec_ms = (time.perf_counter() - t_warm) * 1000
        rt.output = saved_output

    if do_speculate:
        execute_ms = warm_exec_ms if warm_exec_ms is not None else max(0.001, raw_execute_ms - jit_compile_ms)
    else:
        execute_ms = raw_execute_ms

    telemetry = {
        'frontend': 'C teaching subset' if is_c else '.sjit',
        'mode': mode or ('guarded' if do_speculate else 'optimized' if do_optimize else 'default'),
        'source_bytes': len(source.encode('utf-8')),
        'functions': len(program.functions),
        'parse_ms': round(parse_ms, 3),
        'optimization_ms': round(optimize_ms, 3),
        'ssa_ms': round(ir_ms, 3),
        'compile_ms': round(jit_compile_ms, 3),
        'execution_ms': round(execute_ms, 3),
        'total_ms': round((time.perf_counter() - started) * 1000, 3),
        'outputs': len(rt.output),
        'tier_events': len(rt.events)
    }
    return {
        'output': rt.output,
        'ssa': ir,
        'ssa_graphs': ssa_graphs,
        'profile': profile_data(rt),
        'events': rt.events,
        'passes': manager.dumps,
        'stats': manager.stats,
        'telemetry': telemetry,
        'success': True
    }

def compare_modes(data):
    source = data.get('source', '')
    is_c = detect_is_c(source, data.get('c'))
    payload = {**data, 'c': is_c}

    rows = {}
    for mode in ('baseline', 'optimized', 'guarded'):
        try:
            result = execute_source({**payload, 'mode': mode})
            rows[mode] = {
                'output': result['output'],
                'telemetry': result['telemetry'],
                'profile': result['profile'],
                'events': result['events'],
                'ssa': result['ssa'],
                'ssa_graphs': result.get('ssa_graphs', {}),
                'passes': result['passes']
            }
        except Exception as exc:
            rows[mode] = {'error': f'{type(exc).__name__}: {exc}'}

    outputs = [rows[m].get('output') for m in rows if 'output' in rows[m]]
    complete = all('error' not in row for row in rows.values())
    equivalent = complete and len(outputs) == 3 and (outputs[0] == outputs[1] == outputs[2])

    compilers = compiler_status()
    native_desc = 'Available (MSVC cl.exe)' if compilers.get('c') else 'Unavailable (no native compiler detected)'

    return {
        'equivalent': equivalent,
        'modes': rows,
        'native_compiler': native_desc,
        'is_c': is_c
    }

def run_unit_tests():
    proc = subprocess.run(
        [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
        cwd=ROOT, capture_output=True, text=True, timeout=90, shell=False
    )
    raw_out = proc.stdout + '\n' + proc.stderr
    test_items = []
    for line in raw_out.splitlines():
        if ' ... ok' in line or ' ... FAIL' in line or ' ... ERROR' in line:
            status = 'PASS' if ' ... ok' in line else 'FAIL'
            left = line.split(' ... ')[0].strip()
            if '(' in left and left.endswith(')'):
                t_name, suite_info = left[:-1].split(' (', 1)
                suite_parts = suite_info.split('.')
                suite_class = suite_parts[1] if len(suite_parts) > 1 else suite_parts[0]
                suite_mod = suite_parts[0]
            else:
                t_name = left
                suite_class = 'Unittest'
                suite_mod = 'tests'
            test_items.append({
                'name': t_name,
                'suite': suite_class,
                'module': suite_mod,
                'status': status
            })
    return {
        'passed': proc.returncode == 0,
        'exit_code': proc.returncode,
        'total': len(test_items),
        'tests': test_items,
        'output': raw_out[-12000:]
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(self, value, status=200):
        raw = json.dumps(value, default=str).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == '/api/health':
            return self.send_json({
                'ok': True,
                'build': BUILD_ID,
                'pid': os.getpid(),
                'port': self.server.server_port,
                'root': str(ROOT),
                'native_compilers': compiler_status()
            })
        if self.path == '/' or self.path.startswith('/?'):
            raw = (ROOT / 'dashboard.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
            self.end_headers()
            self.wfile.write(raw)
            return
        if self.path == '/api/samples':
            return self.send_json(SAMPLES)
        if self.path == '/api/overview':
            compilers = compiler_status()
            c_info = compilers.get('c', {})
            native_label = f"Installed ({c_info.get('family', 'MSVC')})" if c_info else "Not detected"
            return self.send_json({
                'features': {
                    'Handwritten .sjit frontend': 'Implemented',
                    'C teaching subset / SSA': 'Implemented',
                    'C and C++ system compiler comparison': f'MSVC / Clang / GCC: {native_label}',
                    'CFG and verified SSA': 'Implemented',
                    'AST optimization passes': 'Implemented (safe loops/constants)',
                    'Guarded Python bytecode tier': 'Implemented; Python executor, not native machine code',
                    'Precise mid-function deoptimization': 'Entry-restart approximation',
                    'Native JIT backend': 'Not implemented; Python bytecode only'
                },
                'commands': [
                    'python -m unittest discover -s tests -v',
                    'python benchmarks/run_benchmarks.py',
                    'python "M:\\projects\\comp project\\review3_compiler_sprint\\dashboard.py"'
                ]
            })
        if self.path == '/api/benchmark':
            from benchmarks.run_benchmarks import run_benchmark
            return self.send_json(run_benchmark())
        if self.path == '/api/tests':
            return self.send_json(run_unit_tests())
        if self.path.startswith('/api/demo'):
            from urllib.parse import parse_qs, urlparse
            query = parse_qs(urlparse(self.path).query)
            key = query.get('name', ['loop'])[0]
            demos = {
                'loop': 'examples/loop.c',
                'branches': 'examples/branches.c',
                'optimization': 'examples/arithmetic.c',
                'deoptimization': 'examples/deopt_demo.sjit'
            }
            path = demos.get(key)
            if not path:
                return self.send_json({'error': 'Unknown demo'}, 400)
            source = (ROOT / path).read_text(encoding='utf-8')
            demo_data = {'source': source, 'c': path.endswith('.c'), 'optimize': True, 'mode': 'guarded'}
            res = execute_source(demo_data)
            res['source'] = source
            res['is_c'] = path.endswith('.c')
            res['demo_name'] = key
            return self.send_json(res)
        self.send_json({'error': 'Not found'}, 404)

    def do_POST(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size > 140000:
                return self.send_json({'error': 'Request exceeds 140 KB limit'}, 413)
            data = json.loads(self.rfile.read(size) or b'{}')

            if self.path == '/api/run':
                return self.stream_run(data)

            if self.path == '/api/native-compare':
                from native_runner import native_compare
                lang = data.get('language', 'c')
                src = data.get('source', '')
                result = native_compare(src, lang)

                if lang == 'c':
                    project = compare_modes({'source': src, 'c': True})
                    result['project_modes'] = project['modes']
                    baseline = project['modes'].get('baseline', {})
                    native = result.get('modes', {}).get('native-baseline', {})
                    lines = (native.get('stdout') or '').splitlines()
                    try:
                        printed = [int(line.strip()) for line in lines if line.strip()]
                    except ValueError:
                        printed = None
                    optimized = result.get('modes', {}).get('native-optimized', {})
                    try:
                        optimized_printed = [int(line.strip()) for line in optimized.get('stdout', '').splitlines() if line.strip()]
                    except ValueError:
                        optimized_printed = None

                    result['cross_engine_equivalent'] = (
                        project['equivalent']
                        and baseline.get('output') == printed == optimized_printed
                    ) if result.get('available') and 'error' not in baseline and printed is not None and not optimized.get('error') else None
                else:
                    result['project_modes'] = {
                        'error': 'The project SSA/JIT frontend is a C teaching subset; C++ is compared through native baseline and optimized builds only.'
                    }
                    result['cross_engine_equivalent'] = None
                return self.send_json(result)

            if self.path == '/api/compare':
                return self.send_json(compare_modes(data))

            if self.path == '/api/tests':
                return self.send_json(run_unit_tests())

            if self.path == '/api/demo':
                demos = {
                    'loop': 'examples/loop.c',
                    'branches': 'examples/branches.c',
                    'optimization': 'examples/arithmetic.c',
                    'deoptimization': 'examples/deopt_demo.sjit'
                }
                key = data.get('name')
                path = demos.get(key)
                if not path:
                    return self.send_json({'error': 'Unknown demo'}, 400)
                source = (ROOT / path).read_text(encoding='utf-8')
                demo_data = {'source': source, 'c': path.endswith('.c'), 'optimize': True, 'mode': 'guarded'}
                res = execute_source(demo_data)
                res['source'] = source
                res['is_c'] = path.endswith('.c')
                res['demo_name'] = key
                return self.send_json(res)

            if self.path == '/api/benchmark':
                from benchmarks.run_benchmarks import run_benchmark
                return self.send_json(run_benchmark())

            self.send_json({'error': 'Not found'}, 404)
        except subprocess.TimeoutExpired:
            self.send_json({'error': 'Operation timed out'}, 504)
        except Exception as exc:
            self.send_json({'error': str(exc)}, 400)

    def run_source(self, data):
        return self.send_json(execute_source(data))

    def stream_run(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/x-ndjson; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True

        def emit(item):
            try:
                self.wfile.write((json.dumps(item, default=str) + '\n').encode('utf-8'))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        try:
            emit({'type': 'status', 'message': 'Parsing and preparing program…'})
            result = execute_source(data, event_callback=lambda msg: emit({'type': 'event', 'event': msg}))
            emit({'type': 'result', 'result': result})
        except Exception as exc:
            emit({'type': 'error', 'error': str(exc)})


class LocalDashboardServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except OSError:
                pass
        super().server_bind()


def probe_port(port: int):
    """Check if a port is in use and whether a dashboard is running on it."""
    try:
        conn = HTTPConnection('127.0.0.1', port, timeout=0.6)
        conn.request('GET', '/api/health', headers={'Connection': 'close'})
        resp = conn.getresponse()
        data = json.loads(resp.read().decode('utf-8'))
        conn.close()
        return {'state': 'dashboard', 'build': data.get('build'), 'pid': data.get('pid')}
    except Exception:
        # Check if TCP port is open for something else
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.3)
        try:
            sock.connect(('127.0.0.1', port))
            return {'state': 'occupied'}
        except (OSError, socket.timeout):
            return {'state': 'free'}
        finally:
            sock.close()


def main():
    # Allow optional command line port override: python dashboard.py --port 8765
    chosen_port = None
    if '--port' in sys.argv:
        try:
            chosen_port = int(sys.argv[sys.argv.index('--port') + 1])
        except (IndexError, ValueError):
            print("Invalid --port argument. Expected integer port.")

    ports_to_try = [chosen_port] if chosen_port else list(PREFERRED_PORTS)

    print("Checking ports for active or stale dashboard instances...", flush=True)
    server = None
    for port in ports_to_try:
        probe = probe_port(port)
        if probe['state'] == 'dashboard':
            stale_build = probe.get('build', 'unknown')
            stale_pid = probe.get('pid', 'unknown')
            print(f"  [STALE INSTANCE] Port {port} is held by a Review 3 dashboard instance (PID {stale_pid}, build '{stale_build}').", flush=True)
            print(f"                   To close it, run in PowerShell: Stop-Process -Id {stale_pid} -Force", flush=True)
            continue
        elif probe['state'] == 'occupied':
            print(f"  [PORT IN USE] Port {port} is occupied by another process.", flush=True)
            continue

        try:
            server = LocalDashboardServer(('127.0.0.1', port), Handler)
            break
        except OSError as exc:
            print(f"  Port {port} could not be bound: {exc}", flush=True)

    if server is None:
        # Fallback to dynamic OS port allocation if all preferred ports were busy
        try:
            server = LocalDashboardServer(('127.0.0.1', 0), Handler)
            print(f"  Allocated dynamic port {server.server_port}.", flush=True)
        except OSError as exc:
            raise SystemExit(f"No dashboard port available: {exc}. Stop running dashboard processes and retry.")

    url = f"http://127.0.0.1:{server.server_port}"
    compilers = compiler_status()
    msvc_info = compilers.get('c', {})
    msvc_label = f"Available ({msvc_info.get('family', 'MSVC').upper()})" if msvc_info else "Not visible on PATH (run from Developer Command Prompt or VS Code terminal)"

    print("==================================================================", flush=True)
    print("◈ Review 3 Compiler Dashboard", flush=True)
    print(f"  Build ID:     {BUILD_ID}", flush=True)
    print(f"  Process PID:  {os.getpid()}", flush=True)
    print(f"  Local URL:    {url}", flush=True)
    print(f"  Native MSVC:  {msvc_label}", flush=True)
    print("------------------------------------------------------------------", flush=True)
    print("  Keep this console window open while using the dashboard.", flush=True)
    print("  Press Ctrl+C to stop the dashboard server.", flush=True)
    print("==================================================================", flush=True)

    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        conn = HTTPConnection('127.0.0.1', server.server_port, timeout=4)
        conn.request('GET', '/api/overview', headers={'Connection': 'close'})
        response = conn.getresponse()
        response.read()
        conn.close()
        print(f"Local HTTP self-check: HTTP {response.status} OK", flush=True)
        webbrowser.open(url)
    except Exception as exc:
        print(f"Local HTTP self-check warning: {type(exc).__name__}: {exc}", flush=True)

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nStopping dashboard server...", flush=True)
        server.shutdown()
        server.server_close()
        print("Dashboard stopped cleanly.", flush=True)

if __name__ == '__main__':
    main()
