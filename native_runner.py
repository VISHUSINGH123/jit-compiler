"""Optional local comparison against an installed system C/C++ compiler."""
from __future__ import annotations

from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter
import os
import re
import shutil
import subprocess

MAX_SOURCE_BYTES = 128_000
COMPILE_TIMEOUT_SECONDS = 30
RUN_TIMEOUT_SECONDS = 8
RUN_TRIALS = 5

_MSVC_INITIALIZED = False


def _init_msvc_environment():
    """Attempt to find and initialize the local MSVC environment if cl is not on PATH."""
    global _MSVC_INITIALIZED
    if shutil.which('cl.exe') or shutil.which('cl'):
        return shutil.which('cl.exe') or shutil.which('cl')
    if _MSVC_INITIALIZED:
        return None
    _MSVC_INITIALIZED = True

    # Check vswhere.exe if available
    install_path = None
    vswhere = Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Microsoft Visual Studio' / 'Installer' / 'vswhere.exe'
    if vswhere.exists():
        try:
            res = subprocess.run(
                [str(vswhere), '-latest', '-products', '*', '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath'],
                capture_output=True, text=True, timeout=5
            )
            out = res.stdout.strip()
            if out and Path(out).exists():
                install_path = Path(out)
        except Exception:
            pass

    # Common Visual Studio installation paths
    if not install_path:
        for p in [
            r"C:\Program Files\Microsoft Visual Studio\18\Community",
            r"C:\Program Files\Microsoft Visual Studio\2022\Community",
            r"C:\Program Files\Microsoft Visual Studio\2022\Enterprise",
            r"C:\Program Files\Microsoft Visual Studio\2022\Professional",
            r"C:\Program Files\Microsoft Visual Studio\2022\BuildTools",
            r"C:\Program Files (x86)\Microsoft Visual Studio\2019\Community",
            r"C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools",
        ]:
            if Path(p).exists():
                install_path = Path(p)
                break

    if not install_path:
        return None

    vcvars = install_path / 'VC' / 'Auxiliary' / 'Build' / 'vcvarsall.bat'
    if not vcvars.exists():
        return None

    try:
        cmd = f'call "{vcvars}" x64 >nul && set'
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                if '=' in line:
                    k, v = line.split('=', 1)
                    os.environ[k] = v
            return shutil.which('cl.exe') or shutil.which('cl')
    except Exception:
        pass
    return None


def find_compiler(language: str):
    if language not in ('c', 'cpp'):
        raise ValueError('Language must be c or cpp')
    # Try directly on PATH first, then try auto-initializing MSVC
    candidates = ('cl.exe', 'cl', 'clang.exe', 'clang', 'gcc.exe', 'gcc') if language == 'c' else ('cl.exe', 'cl', 'clang++.exe', 'clang++', 'g++.exe', 'g++')
    for name in candidates:
        path = shutil.which(name)
        if path:
            family = 'msvc' if Path(path).name.lower() in ('cl', 'cl.exe') else 'clang' if 'clang' in Path(path).name.lower() else 'gcc'
            return family, path

    # If no compiler was found in PATH, try locating MSVC via vswhere / vcvarsall
    cl_path = _init_msvc_environment()
    if cl_path:
        return 'msvc', cl_path
    return None


def compiler_status():
    return {lang: ({'family': found[0], 'path': found[1]} if (found := find_compiler(lang)) else None) for lang in ('c', 'cpp')}


def _compile_command(family, compiler, language, optimization, source, output):
    if family == 'msvc':
        level = '/O2' if optimization else '/Od'
        args = [compiler, '/nologo', level]
        if language == 'cpp':
            args.extend(['/EHsc', '/std:c++20'])
        return args + [source, f'/Fe:{output}']
    level = '-O2' if optimization else '-O0'
    standard = '-std=c++20' if language == 'cpp' else '-std=c11'
    return [compiler, level, standard, source, '-o', output]


def _run(executable, cwd):
    started = perf_counter()
    result = subprocess.run([str(executable)], cwd=cwd, capture_output=True,
                            timeout=RUN_TIMEOUT_SECONDS, shell=False)
    elapsed = (perf_counter() - started) * 1000
    return result.returncode, result.stdout[:65536].decode('utf-8', 'replace'), result.stderr[:65536].decode('utf-8', 'replace'), elapsed


def _version(family, compiler):
    command = [compiler] if family == 'msvc' else [compiler, '--version']
    try:
        result = subprocess.run(command, capture_output=True, timeout=5, shell=False)
        # MSVC cl outputs version banner to stderr; gcc/clang to stdout
        text = (result.stderr + result.stdout).decode('utf-8', 'replace')
        if family == 'msvc':
            for line in text.splitlines():
                stripped = line.strip()
                if 'Optimizing Compiler Version' in stripped or 'Compiler Version' in stripped:
                    return stripped
        return next((line.strip() for line in text.splitlines() if line.strip() and not line.strip().lower().startswith('usage:')), family)
    except (OSError, subprocess.TimeoutExpired):
        return family


def native_compare(source: str, language: str):
    if language not in ('c', 'cpp'):
        raise ValueError('Choose C or C++')
    if not isinstance(source, str) or not source.strip():
        raise ValueError('Enter C/C++ source before native compilation')
    if len(source.encode('utf-8')) > MAX_SOURCE_BYTES:
        raise ValueError('Native source limit is 128 KB')

    # Detect .sjit syntax to prevent sending toy AST language to MSVC/C compiler
    if re.search(r'\b(?:fn\s+[A-Za-z_]|let\s+[A-Za-z_]|print\s*\()', source):
        return {
            'available': False,
            'language': language,
            'error': (
                "The editor contains project .sjit language syntax ('fn' / 'let' / 'print'), not standard C/C++. "
                "The Native Compiler panel sends code to the installed MSVC/system compiler, which requires valid C/C++ syntax "
                "(e.g. '#include <stdio.h>', 'int main(void)').\n\n"
                "👉 To run this .sjit code: Use '▶ Run selected mode' or 'Compare project modes'.\n"
                "👉 To use MSVC: Load a C sample (e.g. 'C Branches' or 'C For Loop (Regression)') or paste standard C/C++ source code."
            )
        }

    detected = find_compiler(language)
    if not detected:
        label = 'C' if language == 'c' else 'C++'
        return {
            'available': False,
            'language': language,
            'error': f'No native {label} compiler is visible to this dashboard process. Start it from the VS Code terminal where cl/gcc/clang works, or configure MSVC.'
        }

    family, compiler = detected
    version_started = perf_counter()
    version = _version(family, compiler)
    version_probe_ms = (perf_counter() - version_started) * 1000
    suffix = '.c' if language == 'c' else '.cpp'
    results = {}

    # Keep temporary native build files inside the project workspace
    with TemporaryDirectory(prefix='review3-native-', dir=Path(__file__).resolve().parent) as temp:
        root = Path(temp)
        source_path = root / ('program' + suffix)
        source_path.write_text(source, encoding='utf-8')
        for name, optimized in (('native-baseline', False), ('native-optimized', True)):
            binary = root / (name + ('.exe' if family == 'msvc' or os.name == 'nt' else ''))
            command = _compile_command(family, compiler, language, optimized, str(source_path), str(binary))
            compile_started = perf_counter()
            try:
                built = subprocess.run(command, cwd=root, capture_output=True, timeout=COMPILE_TIMEOUT_SECONDS, shell=False)
            except subprocess.TimeoutExpired:
                results[name] = {'error': 'Compilation timed out', 'compile_ms': None}
                continue
            except OSError as exc:
                results[name] = {'error': f'Compiler launch error: {exc}', 'compile_ms': None}
                continue

            compile_ms = (perf_counter() - compile_started) * 1000
            build_text = (built.stdout + built.stderr)[:65536].decode('utf-8', 'replace')
            if built.returncode != 0 or not binary.exists():
                results[name] = {'error': f'Compiler exited {built.returncode}', 'compile_ms': round(compile_ms, 3), 'compiler_output': build_text}
                continue

            try:
                # One untimed warm-up, then repeated whole-process timings.
                warmup = _run(binary, root)
                trials = [_run(binary, root) for _ in range(RUN_TRIALS)]
            except subprocess.TimeoutExpired:
                results[name] = {'error': f'Program exceeded {RUN_TIMEOUT_SECONDS}s timeout', 'compile_ms': round(compile_ms, 3), 'compiler_output': build_text}
                continue
            except OSError as exc:
                results[name] = {'error': f'Execution error: {exc}', 'compile_ms': round(compile_ms, 3), 'compiler_output': build_text}
                continue

            results[name] = {
                'compile_ms': round(compile_ms, 3),
                'runtime_median_ms': round(median(x[3] for x in trials), 3),
                'runtime_trials_ms': [round(x[3], 3) for x in trials],
                'warmup_ms': round(warmup[3], 3),
                'stdout': warmup[1],
                'stderr': warmup[2],
                'exit_code': warmup[0],
                'stable_across_trials': len(set((x[0], x[1], x[2]) for x in trials)) == 1,
                'binary_bytes': binary.stat().st_size,
                'compiler_output': build_text,
            }

    baseline = results.get('native-baseline', {})
    optimized = results.get('native-optimized', {})
    equivalent = (
        not baseline.get('error')
        and not optimized.get('error')
        and baseline.get('exit_code') == optimized.get('exit_code')
        and baseline.get('stdout') == optimized.get('stdout')
        and baseline.get('stderr') == optimized.get('stderr')
    )
    return {
        'available': True,
        'language': language,
        'compiler_family': family,
        'compiler_path': compiler,
        'compiler_version': version,
        'version_probe_ms': round(version_probe_ms, 3),
        'optimization_flags': {
            'native-baseline': '/Od' if family == 'msvc' else '-O0',
            'native-optimized': '/O2' if family == 'msvc' else '-O2'
        },
        'equivalent': equivalent,
        'trials': RUN_TRIALS,
        'modes': results,
        'execution_scope': (
            'Local native executable, temporary working directory, 8-second timeout; '
            'user code runs with dashboard process permissions. '
            'Timings report whole-process execution (process startup, runtime init, execution, exit) '
            'across 5 repeated trials after 1 untimed warm-up run.'
        )
    }
