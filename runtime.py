from collections import defaultdict
from dataclasses import dataclass
from parser import *
from py_executor import compile_plan, UnsupportedPlan
from time import perf_counter_ns

class RuntimeFault(Exception): pass
class DeoptSignal(Exception):
    def __init__(self, reason, snapshot):
        self.reason = reason
        self.snapshot = snapshot

@dataclass
class CompiledVersion:
    function: Function
    guarded_types: tuple
    optimized: bool = True
    compile_number: int = 1
    executor: object = None
    source: str = ""
    compile_ns: int = 0

class Runtime:
    def __init__(self, program, hot_threshold=3, deopt_budget=2, event_callback=None):
        self.program = program
        self.hot_threshold = hot_threshold
        self.deopt_budget = deopt_budget
        self.profile = defaultdict(lambda: {
            "calls": 0, "arg_types": defaultdict(int), "branches": defaultdict(int),
            "loop_iterations": 0, "deopts": 0, "failed_type_signatures": set(),
            "compile_count": 0, "compile_ns": 0, "jit_status": "interpreting"
        })
        self.code_cache = {}
        self.output = []
        self.events = []
        self.event_callback = event_callback
        self.compiled_calls = defaultdict(int)

    def record_event(self, message):
        self.events.append(message)
        if self.event_callback:
            try:
                self.event_callback(message)
            except (BrokenPipeError, ConnectionResetError):
                self.event_callback = None

    def run(self):
        for stmt in self.program.statements:
            self.exec_stmt(stmt, {})
        return self.output

    def call(self, name, args):
        if name not in self.program.functions:
            raise RuntimeFault(f"Unknown function: {name}")
        f = self.program.functions[name]
        if len(args) != len(f.params):
            raise RuntimeFault(f"{name} expects {len(f.params)} arguments, got {len(args)}")
        p = self.profile[name]
        p["calls"] += 1
        sig = tuple(type(x).__name__ for x in args)
        for typ in sig: p["arg_types"][typ] += 1
        version = self.code_cache.get(name)
        if version:
            try:
                return self.execute_compiled(version, args, sig)
            except DeoptSignal as d:
                return self._recover_deopt(name,f,args,sig,d)
        if p["calls"] >= self.hot_threshold and p["jit_status"] != "interpreter-only (deopt budget exhausted)":
            self.compile_function(f, sig)
            version = self.code_cache.get(name)
            if version:
                try: return self.execute_compiled(version, args, sig)
                except DeoptSignal as d:
                    return self._recover_deopt(name,f,args,sig,d)
        return self.execute_function(f, args, mode="interpreter")

    def fast_call(self, name, *args):
        v = self.code_cache.get(name)
        if v is not None:
            sig = tuple(type(x).__name__ for x in args)
            if sig == v.guarded_types:
                self.compiled_calls[name] += 1
                try:
                    return v.executor(self, *args)
                except (ZeroDivisionError, TypeError) as e:
                    raise RuntimeFault(str(e))
        return self.call(name, list(args))

    def _recover_deopt(self,name,f,args,sig,deopt):
        p=self.profile[name];p["deopts"]+=1
        self.record_event(f"DEOPT {name}: stage=compiled-entry-type-guard; reason={deopt.reason}; action=discard-specialized-version,restart-in-interpreter-at-function-entry; snapshot={deopt.snapshot}")
        self.code_cache.pop(name,None)
        if p["deopts"]>=self.deopt_budget:
            p["jit_status"]="interpreter-only (deopt budget exhausted)"
            self.record_event(f"POLICY {name}: stage=post-deoptimization; action=disable-specialization,continue-in-interpreter; reason=deoptimization-budget-exhausted")
        else:
            self.record_event(f"RECOMPILE {name}: stage=post-recovery; action=compile-new-guarded-version; observed_signature={sig}")
            self.compile_function(f,sig)
        return self.execute_function(f,args,mode="interpreter")

    def compile_function(self, f, sig):
        p = self.profile[f.name]
        # Adaptive feedback: don't repeatedly speculate on a signature already known to fail.
        if sig in p["failed_type_signatures"]:
            p["jit_status"] = "conservative (known failing signature)"
            self.record_event(f"RECOMPILE {f.name}: skipped risky type signature {sig}")
            return
        start=perf_counter_ns()
        try:
            executor,source=compile_plan(f)
        except UnsupportedPlan as exc:
            p["jit_status"] = f"interpreter-only (unsupported plan: {exc})"
            return
        elapsed=perf_counter_ns()-start
        p["compile_count"] += 1
        self.code_cache[f.name] = CompiledVersion(f, sig, True, p["compile_count"], executor, source, elapsed)
        p["jit_status"] = "Python bytecode plan (guarded; not native)"
        p["compile_ns"] += elapsed
        self.record_event(f"JIT {f.name}: stage=hot-call; compiled Python bytecode plan {p['compile_count']} ({elapsed} ns), entry_guards={sig}")

    def execute_compiled(self, version, args, sig=None):
        if sig is None:
            sig = tuple(type(x).__name__ for x in args)
        if sig != version.guarded_types:
            snapshot = {"function": version.function.name,
                        "locals_at_entry": dict(zip(version.function.params, args)),
                        "resume": "restart at function entry"}
            raise DeoptSignal(f"expected argument types {version.guarded_types}, observed {sig}", snapshot)
        self.compiled_calls[version.function.name] += 1
        try:
            return version.executor(self, *args)
        except (ZeroDivisionError, TypeError) as e:
            raise RuntimeFault(str(e))

    def _compiled_print(self, args):
        self.output.append(args[0] if args else None)
        return None

    @staticmethod
    def _loop_fault():
        return RuntimeFault("Loop iteration safety limit exceeded")

    def execute_function(self, f, args, mode):
        env = dict(zip(f.params, args))
        try:
            for stmt in f.body:
                self.exec_stmt(stmt, env, mode, f.name)
        except _ReturnValue as r:
            return r.value
        return None

    def eval_expr(self, e, env, mode="interpreter", fn_name=None):
        if isinstance(e, Number): return e.value
        if isinstance(e, Bool): return e.value
        if isinstance(e, Var):
            if e.name not in env: raise RuntimeFault(f"Undefined variable: {e.name}")
            return env[e.name]
        if isinstance(e, Call):
            args = [self.eval_expr(a, env, mode, fn_name) for a in e.args]
            if e.name == "print":
                self.output.append(args[0] if args else None); return None
            return self.call(e.name, args)
        if isinstance(e, Unary):
            v = self.eval_expr(e.expr, env, mode, fn_name)
            if e.op == "-": return -v
            if e.op == "!": return not v
        if isinstance(e, Binary):
            a = self.eval_expr(e.left, env, mode, fn_name)
            b = self.eval_expr(e.right, env, mode, fn_name)
            # Small constant-folding demonstration: literal-only expressions are folded by parser tree shape.
            if mode == "optimized" and isinstance(e.left, Number) and isinstance(e.right, Number):
                self.record_event(f"OPT {fn_name}: constant-folded {e.left.value} {e.op} {e.right.value}")
            return self.apply_op(e.op, a, b)
        raise RuntimeFault(f"Unsupported expression: {type(e).__name__}")

    def apply_op(self, op, a, b):
        try:
            return {"+":lambda:a+b, "-":lambda:a-b, "*":lambda:a*b,
                    "/":lambda:a//b, "%":lambda:a%b, "==":lambda:a==b,
                    "!=":lambda:a!=b, "<":lambda:a<b, "<=":lambda:a<=b,
                    ">":lambda:a>b, ">=":lambda:a>=b,
                    "&&":lambda:bool(a) and bool(b), "||":lambda:bool(a) or bool(b)}[op]()
        except KeyError: raise RuntimeFault(f"Unknown operator {op}")
        except (ZeroDivisionError, TypeError) as e: raise RuntimeFault(str(e))

    def exec_stmt(self, s, env, mode="interpreter", fn_name=None):
        if isinstance(s, Let):
            env[s.name] = self.eval_expr(s.expr, env, mode, fn_name)
        elif isinstance(s, Assign):
            if s.name not in env: raise RuntimeFault(f"Assignment to undefined variable: {s.name}")
            env[s.name] = self.eval_expr(s.expr, env, mode, fn_name)
        elif isinstance(s, Return):
            raise _ReturnValue(self.eval_expr(s.expr, env, mode, fn_name))
        elif isinstance(s, ExprStmt):
            self.eval_expr(s.expr, env, mode, fn_name)
        elif isinstance(s, If):
            cond = self.eval_expr(s.cond, env, mode, fn_name)
            if fn_name and mode != "optimized":
                key = "true" if cond else "false"
                self.profile[fn_name]["branches"][key] += 1
            for stmt in (s.then_body if cond else s.else_body):
                self.exec_stmt(stmt, env, mode, fn_name)
        elif isinstance(s, While):
            iterations = 0
            while self.eval_expr(s.cond, env, mode, fn_name):
                iterations += 1
                if iterations > 100000: raise RuntimeFault("Loop iteration safety limit exceeded")
                if fn_name and mode != "optimized": self.profile[fn_name]["loop_iterations"] += 1
                for stmt in s.body: self.exec_stmt(stmt, env, mode, fn_name)
        else:
            raise RuntimeFault(f"Unsupported statement: {type(s).__name__}")

    def report(self):
        lines = ["=== Runtime Profile ==="]
        for name, p in self.profile.items():
            lines.append(f"{name}: calls={p['calls']}, arg_types={dict(p['arg_types'])}, "
                         f"branches={dict(p['branches'])}, loop_iterations={p['loop_iterations']}, "
                         f"compiled_calls={self.compiled_calls[name]}, compile_ms={p['compile_ns']/1e6:.4f}, "
                         f"deopts={p['deopts']}, compiles={p['compile_count']}, status={p['jit_status']}")
        lines.append("\n=== JIT / Deoptimization Events ===")
        lines.extend(self.events or ["No JIT/deoptimization events yet."])
        return "\n".join(lines)

class _ReturnValue(Exception):
    def __init__(self, value): self.value = value
