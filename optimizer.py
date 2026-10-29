"""Conservative AST optimization passes for the supported toy language."""
from dataclasses import replace
from parser import Number, Bool, Var, Unary, Binary, Call, Let, Assign, Return, ExprStmt, If, While

def fold_expr(e):
    """Constant-fold safe literal-only arithmetic/comparison expressions."""
    if isinstance(e, Unary):
        x = fold_expr(e.expr)
        if isinstance(x, Number):
            if e.op == '-': return Number(-x.value)
            if e.op == '!': return Bool(not x.value)
        if isinstance(x, Bool) and e.op == '!': return Bool(not x.value)
        return Unary(e.op, x)
    if isinstance(e, Binary):
        a, b = fold_expr(e.left), fold_expr(e.right)
        if isinstance(a, (Number, Bool)) and isinstance(b, (Number, Bool)):
            av, bv = a.value, b.value
            try:
                ops = {
                    '+': lambda: av + bv, '-': lambda: av - bv,
                    '*': lambda: av * bv, '/': lambda: av // bv,
                    '%': lambda: av % bv, '==': lambda: av == bv,
                    '!=': lambda: av != bv, '<': lambda: av < bv,
                    '<=': lambda: av <= bv, '>': lambda: av > bv,
                    '>=': lambda: av >= bv,
                }
                if e.op in ops:
                    value = ops[e.op]()
                    return Bool(value) if isinstance(value, bool) else Number(value)
            except (ZeroDivisionError, TypeError):
                pass
        return Binary(a, e.op, b)
    if isinstance(e, Call):
        return Call(e.name, [fold_expr(x) for x in e.args])
    return e

def _substitute(e, constants):
    if isinstance(e, Var):
        return constants.get(e.name, e)
    if isinstance(e, Unary):
        return fold_expr(Unary(e.op, _substitute(e.expr, constants)))
    if isinstance(e, Binary):
        return fold_expr(Binary(_substitute(e.left, constants), e.op, _substitute(e.right, constants)))
    if isinstance(e, Call):
        return Call(e.name, [_substitute(x, constants) for x in e.args])
    return e

def optimize_statements(stmts):
    """Constant propagation/folding plus conservative dead-tail elimination."""
    constants = {}
    out = []
    terminated = False
    for s in stmts:
        if terminated:
            continue
        if isinstance(s, Let):
            expr = fold_expr(_substitute(s.expr, constants))
            out.append(Let(s.name, expr))
            if isinstance(expr, (Number, Bool)): constants[s.name] = expr
            else: constants.pop(s.name, None)
        elif isinstance(s, Assign):
            expr = fold_expr(_substitute(s.expr, constants))
            out.append(Assign(s.name, expr))
            if isinstance(expr, (Number, Bool)): constants[s.name] = expr
            else: constants.pop(s.name, None)
        elif isinstance(s, Return):
            out.append(Return(fold_expr(_substitute(s.expr, constants))))
            terminated = True
        elif isinstance(s, ExprStmt):
            out.append(ExprStmt(fold_expr(_substitute(s.expr, constants))))
        elif isinstance(s, If):
            cond = fold_expr(_substitute(s.cond, constants))
            if isinstance(cond, Bool):
                chosen = s.then_body if cond.value else s.else_body
                out.extend(optimize_statements(chosen))
                if chosen and isinstance(chosen[-1], Return): terminated = True
            else:
                out.append(If(cond, optimize_statements(s.then_body), optimize_statements(s.else_body)))
                # A branch may mutate any variable; conservatively clear facts.
                constants.clear()
        elif isinstance(s, While):
            # A loop can mutate any variable referenced by its condition or
            # within its body across iterations. To prevent infinite loops and
            # false constant propagation, clear pre-loop constants before
            # analyzing the loop condition and loop body.
            constants.clear()
            cond = fold_expr(s.cond)
            if isinstance(cond, Bool) and not cond.value:
                continue
            out.append(While(cond, optimize_statements(s.body)))
            constants.clear()
        else:
            out.append(s)
    return out

def optimize_program(program):
    """Return a new program AST optimized function-by-function and at top level."""
    from parser import Program, Function
    result = Program()
    result.functions = {
        name: Function(fn.name, list(fn.params), optimize_statements(fn.body))
        for name, fn in program.functions.items()
    }
    result.statements = optimize_statements(program.statements)
    return result

class PassManager:
    """Deterministic AST pass pipeline with optional before/after snapshots.

    The passes are deliberately named by their actual scope: these are AST
    transformations, while verified SSA construction is provided by ssa.py.
    """
    def __init__(self, passes=None):
        self.passes = passes or [("constant-fold/propagate", optimize_program),
                                 ("copy-propagation", copy_program),
                                 ("common-subexpression-elimination", cse_program),
                                 ("dead-code-elimination", dce_program)]
        self.dumps = []
        self.stats = []
    def run(self, program):
        current = program
        for name, transform in self.passes:
            before = _ir_snapshot(current)
            current = transform(current)
            after=_ir_snapshot(current)
            self.dumps.append({"pass": name, "before": before, "after": after})
            self.stats.append({"pass":name,"changed":before!=after,"before_chars":len(before),"after_chars":len(after)})
        return current

def _format_expr(e):
    if e is None:
        return 'null'
    if isinstance(e, Number):
        return str(e.value)
    if isinstance(e, Bool):
        return 'true' if e.value else 'false'
    if isinstance(e, Var):
        return e.name
    if isinstance(e, Unary):
        return f"{e.op}{_format_expr(e.expr)}"
    if isinstance(e, Binary):
        return f"({_format_expr(e.left)} {e.op} {_format_expr(e.right)})"
    if isinstance(e, Call):
        args = ', '.join(_format_expr(a) for a in e.args)
        return f"{e.name}({args})"
    return repr(e)

def _format_stmt(stmt, indent=''):
    if isinstance(stmt, Let):
        return f"{indent}let {stmt.name} = {_format_expr(stmt.expr)};"
    if isinstance(stmt, Assign):
        return f"{indent}{stmt.name} = {_format_expr(stmt.expr)};"
    if isinstance(stmt, Return):
        return f"{indent}return {_format_expr(stmt.expr)};"
    if isinstance(stmt, ExprStmt):
        return f"{indent}{_format_expr(stmt.expr)};"
    if isinstance(stmt, If):
        lines = [f"{indent}if ({_format_expr(stmt.cond)}) {{"]
        for s in (stmt.then_body or []):
            lines.append(_format_stmt(s, indent + '  '))
        if stmt.else_body:
            lines.append(f"{indent}}} else {{")
            for s in stmt.else_body:
                lines.append(_format_stmt(s, indent + '  '))
        lines.append(f"{indent}}}")
        return '\n'.join(lines)
    if isinstance(stmt, While):
        lines = [f"{indent}while ({_format_expr(stmt.cond)}) {{"]
        for s in (stmt.body or []):
            lines.append(_format_stmt(s, indent + '  '))
        lines.append(f"{indent}}}")
        return '\n'.join(lines)
    return f"{indent}{repr(stmt)};"

def _ir_snapshot(program):
    parts = []
    for name, fn in program.functions.items():
        params = ', '.join(fn.params)
        body_lines = [_format_stmt(s, '  ') for s in (fn.body or [])]
        body_str = '\n'.join(body_lines) if body_lines else '  // empty body'
        parts.append(f"fn {name}({params}) {{\n{body_str}\n}}")
    if program.statements:
        top_lines = [_format_stmt(s, '') for s in program.statements]
        parts.append('\n'.join(top_lines))
    return '\n\n'.join(parts)

def _map_program(program, fn):
    from parser import Program, Function
    p=Program();p.functions={n:Function(f.name,list(f.params),fn(f.body)) for n,f in program.functions.items()};p.statements=fn(program.statements);return p

def _vars(e):
    if isinstance(e,Var):return {e.name}
    if isinstance(e,Unary):return _vars(e.expr)
    if isinstance(e,Binary):return _vars(e.left)|_vars(e.right)
    if isinstance(e,Call):return set().union(*(_vars(a) for a in e.args),set())
    return set()

def _pure(e):
    if isinstance(e,(Number,Bool,Var)):return True
    if isinstance(e,Unary):return _pure(e.expr)
    if isinstance(e,Binary):return _pure(e.left) and _pure(e.right)
    return False

def _rewrite(e, aliases):
    if isinstance(e,Var):return aliases.get(e.name,e)
    if isinstance(e,Unary):return Unary(e.op,_rewrite(e.expr,aliases))
    if isinstance(e,Binary):return Binary(_rewrite(e.left,aliases),e.op,_rewrite(e.right,aliases))
    if isinstance(e,Call):return Call(e.name,[_rewrite(a,aliases) for a in e.args])
    return e

def copy_statements(stmts):
    aliases={};out=[]
    for s in stmts:
        if isinstance(s,(Let,Assign)):
            e=_rewrite(s.expr,aliases);aliases={k:v for k,v in aliases.items() if k!=s.name and v.name!=s.name}
            out.append(type(s)(s.name,e))
            if isinstance(e,Var):aliases[s.name]=e
        elif isinstance(s,ExprStmt):out.append(ExprStmt(_rewrite(s.expr,aliases)))
        elif isinstance(s,Return):out.append(Return(_rewrite(s.expr,aliases)))
        elif isinstance(s,If):
            out.append(If(_rewrite(s.cond,aliases),copy_statements(s.then_body),copy_statements(s.else_body)));aliases.clear()
        elif isinstance(s,While):
            # Clear aliases before the loop to prevent pre-loop copies from
            # corrupting the loop condition or body across iterations.
            aliases.clear()
            out.append(While(s.cond,copy_statements(s.body)))
            aliases.clear()
        else:out.append(s)
    return out

def copy_program(program):return _map_program(program,copy_statements)

def cse_statements(stmts):
    available={};out=[]
    for s in stmts:
        if isinstance(s,(Let,Assign)):
            e=fold_expr(s.expr)
            if _pure(e) and repr(e) in available:e=Var(available[repr(e)][0])
            out.append(type(s)(s.name,e))
            available={k:v for k,v in available.items() if s.name not in v[1] and v[0]!=s.name}
            if _pure(e):available[repr(e)]=(s.name,_vars(e))
        elif isinstance(s,If):out.append(If(s.cond,cse_statements(s.then_body),cse_statements(s.else_body)));available.clear()
        elif isinstance(s,While):
            # Invalidate available common subexpressions across loop boundaries.
            available.clear()
            out.append(While(s.cond,cse_statements(s.body)))
            available.clear()
        else:out.append(s)
    return out

def cse_program(program):return _map_program(program,cse_statements)

def _dce_straight(stmts):
    # Without block liveness, preserve all stores in a function containing control flow.
    if any(isinstance(s,(If,While)) for s in stmts):return list(stmts)
    out=[];chunk=[]
    def flush(part):
        live=set(); kept=[]
        for s in reversed(part):
            if isinstance(s,(Let,Assign)):
                if s.name not in live:
                    if not _pure(s.expr):kept.append(ExprStmt(s.expr))
                    continue
                live.discard(s.name);live|=_vars(s.expr);kept.append(s)
            else:
                if isinstance(s,ExprStmt):live|=_vars(s.expr)
                elif isinstance(s,Return):live|=_vars(s.expr)
                kept.append(s)
        return list(reversed(kept))
    for s in stmts:
        chunk.append(s)
    out.extend(flush(chunk));return out

def dce_program(program):return _map_program(program,_dce_straight)
