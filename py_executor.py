"""AST-to-Python-bytecode execution-plan compiler (not native machine code)."""
from parser import Number, Bool, Var, Unary, Binary, Call, Let, Assign, Return, ExprStmt, If, While

class UnsupportedPlan(Exception): pass

def compile_plan(function):
    names=list(function.params)
    def collect(stmts):
        for s in stmts:
            if isinstance(s,(Let,Assign)) and s.name not in names:names.append(s.name)
            elif isinstance(s,If):collect(s.then_body);collect(s.else_body)
            elif isinstance(s,While):collect(s.body)
    collect(function.body)
    def reads(e):
        if isinstance(e,Var):return {e.name}
        if isinstance(e,Unary):return reads(e.expr)
        if isinstance(e,Binary):return reads(e.left)|reads(e.right)
        if isinstance(e,Call):return set().union(*[reads(a) for a in e.args]) if e.args else set()
        return set()
    def check(stmts, assigned):
        assigned=set(assigned)
        for s in stmts:
            if isinstance(s,Let):
                if not reads(s.expr)<=assigned:raise UnsupportedPlan('read before assignment')
                assigned.add(s.name)
            elif isinstance(s,Assign):
                if s.name not in assigned or not reads(s.expr)<=assigned:raise UnsupportedPlan('assignment/read before definition')
            elif isinstance(s,ExprStmt):
                if not reads(s.expr)<=assigned:raise UnsupportedPlan('read before assignment')
            elif isinstance(s,Return):
                if not reads(s.expr)<=assigned:raise UnsupportedPlan('read before assignment')
            elif isinstance(s,If):
                if not reads(s.cond)<=assigned:raise UnsupportedPlan('read before assignment')
                left=check(s.then_body,assigned);right=check(s.else_body,assigned);assigned=left&right
            elif isinstance(s,While):
                if not reads(s.cond)<=assigned:raise UnsupportedPlan('read before assignment')
                check(s.body,assigned)
        return assigned
    check(function.body,function.params)
    loc={n:f'_v{i}' for i,n in enumerate(names)}
    def expr(e):
        if isinstance(e,Number):return repr(e.value)
        if isinstance(e,Bool):return repr(e.value)
        if isinstance(e,Var):
            if e.name not in loc:raise UnsupportedPlan(f'unknown local {e.name}')
            return loc[e.name]
        if isinstance(e,Unary):
            a=expr(e.expr)
            return f'(-({a}))' if e.op=='-' else f'(not ({a}))'
        if isinstance(e, Binary):
            py_ops = {
                '+': '+', '-': '-', '*': '*', '/': '//', '%': '%',
                '==': '==', '!=': '!=', '<': '<', '<=': '<=',
                '>': '>', '>=': '>=', '&&': 'and', '||': 'or'
            }
            if e.op in py_ops:
                return f'(({expr(e.left)}) {py_ops[e.op]} ({expr(e.right)}))'
            return f'rt.apply_op({e.op!r}, {expr(e.left)}, {expr(e.right)})'
        if isinstance(e,Call):
            args=', '.join(expr(a) for a in e.args)
            if e.name=='print':return f'rt._compiled_print([{args}])'
            return f'rt.fast_call({e.name!r}{", " + args if args else ""})'
        raise UnsupportedPlan(type(e).__name__)
    lines=['    _fault = rt._loop_fault']
    for i,p in enumerate(function.params): lines.append(f'    {loc[p]} = _arg{i}')
    counter=[0]
    def emit(stmts,indent):
        pad=' '*indent
        for s in stmts:
            if isinstance(s,(Let,Assign)):
                if isinstance(s,Assign) and s.name not in loc:raise UnsupportedPlan(f'undefined assignment {s.name}')
                lines.append(f'{pad}{loc[s.name]} = {expr(s.expr)}')
            elif isinstance(s,Return):lines.append(f'{pad}return {expr(s.expr)}')
            elif isinstance(s,ExprStmt):lines.append(f'{pad}{expr(s.expr)}')
            elif isinstance(s,If):
                lines.append(f'{pad}if {expr(s.cond)}:');emit(s.then_body,indent+4)
                if not s.then_body:lines.append(' '*(indent+4)+'pass')
                if s.else_body:lines.append(f'{pad}else:');emit(s.else_body,indent+4)
            elif isinstance(s,While):
                idx=counter[0];counter[0]+=1
                lines.append(f'{pad}_loop{idx} = 0')
                lines.append(f'{pad}while {expr(s.cond)}:')
                lines.append(f'{pad}    _loop{idx} += 1')
                lines.append(f'{pad}    if _loop{idx} > 100000: raise _fault()')
                emit(s.body,indent+4)
                if not s.body:lines.append(' '*(indent+4)+'pass')
            else:raise UnsupportedPlan(type(s).__name__)
    emit(function.body,4)
    if not lines or not any(line.lstrip().startswith('return ') for line in lines):lines.append('    return None')
    args=', '.join(f'_arg{i}' for i in range(len(function.params)))
    source=f'def _compiled(rt{", " if args else ""}{args}):\n'+'\n'.join(lines)+'\n'
    namespace={}
    exec(compile(source,f'<compiled:{function.name}>','exec'),{'__builtins__':{}},namespace)
    return namespace['_compiled'],source
