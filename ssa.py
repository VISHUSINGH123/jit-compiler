"""Small, verified SSA construction for the scalar toy-language subset.

The builder uses explicit CFG blocks, iterative dominators/frontiers, Cytron phi
placement, and dominator-tree renaming. Expressions are retained as AST values
with variable reads rewritten to versioned names.
"""
from dataclasses import dataclass, field
from parser import Number, Bool, Var, Unary, Binary, Call, Let, Assign, Return, ExprStmt, If, While
from cfg import CFG, BasicBlock

@dataclass
class Phi:
    name: str
    result: str
    incoming: dict = field(default_factory=dict)
@dataclass
class SSAInstruction:
    op: str
    result: str | None = None
    value: object = None
@dataclass
class SSAFunction:
    cfg: CFG
    phis: dict
    instructions: dict
    dominators: dict
    frontier: dict
    def dump(self):
        out=[]
        for b in self.cfg.blocks:
            out.append(b.name+':')
            out.append('  dom: '+', '.join(sorted(self.dominators.get(b.name,set()))))
            out.append('  frontier: '+', '.join(sorted(self.frontier.get(b.name,set())) or ['-']))
            for p in self.phis.get(b.name,[]):
                args=', '.join(f'{k}: {v}' for k,v in p.incoming.items())
                out.append(f'  {p.result} = phi({args})')
            for i in self.instructions.get(b.name,[]):
                out.append(f'  {i.result + " = " if i.result else ""}{i.op} {i.value!r}'.rstrip())
            out.append('  preds: '+(', '.join(b.predecessors) or '-'))
            out.append('  succs: '+(', '.join(b.successors) or '-'))
        return '\n'.join(out)

def _expr_vars(e):
    if isinstance(e,Var): return {e.name}
    if isinstance(e,(Number,Bool)): return set()
    if isinstance(e,Unary): return _expr_vars(e.expr)
    if isinstance(e,Binary): return _expr_vars(e.left)|_expr_vars(e.right)
    if isinstance(e,Call):
        s=set()
        for a in e.args:s|=_expr_vars(a)
        return s
    return set()

def _blocks(stmts):
    """Build blocks while retaining AST operations, including correct loop backedges."""
    c=CFG(); c.blocks=[]; c.counter=0; entry=c.new_block('entry'); cur=entry
    def lower(seq,cur):
        for s in seq:
            if cur is None: break
            if isinstance(s,If):
                cur.instructions.append(('branch',s.cond)); t=c.new_block('then'); e=c.new_block('else'); m=c.new_block('merge')
                CFG.edge(cur,t); CFG.edge(cur,e)
                te=lower(s.then_body,t); ee=lower(s.else_body,e)
                if te: CFG.edge(te,m)
                if ee: CFG.edge(ee,m)
                cur=m
            elif isinstance(s,While):
                h=c.new_block('loop_header'); b=c.new_block('loop_body'); x=c.new_block('loop_exit')
                CFG.edge(cur,h); h.instructions.append(('branch',s.cond)); CFG.edge(h,b); CFG.edge(h,x)
                be=lower(s.body,b)
                if be: CFG.edge(be,h)
                cur=x
            else:
                cur.instructions.append(('stmt',s))
                if isinstance(s,Return): cur=None
        return cur
    lower(stmts,cur)
    return c

def build_ssa(stmts, params=()):
    cfg=_blocks(stmts); blocks=cfg.blocks; names={b.name for b in blocks}; entry=cfg.entry.name
    block_order={b.name:i for i,b in enumerate(blocks)}
    pred={b.name:set(b.predecessors) for b in blocks}
    dom={n: ({n} if n==entry else set(names)) for n in names}
    changed=True
    while changed:
        changed=False
        for n in (b.name for b in blocks if b.name!=entry):
            ps=pred[n]; new={n}| (set.intersection(*(dom[p] for p in ps)) if ps else set())
            if new!=dom[n]:dom[n]=new;changed=True
    idom={}
    for n in (b.name for b in blocks if b.name!=entry):
        strict=dom[n]-{n}
        idom[n]=next((d for d in strict if all(d==o or d not in dom[o] for o in strict)), None)
    frontier={n:set() for n in names}
    for b in blocks:
        if len(pred[b.name])>=2:
            for p in pred[b.name]:
                runner=p
                while runner is not None and runner!=idom.get(b.name):
                    frontier[runner].add(b.name); runner=idom.get(runner)
    defs={n:set() for n in names}; allvars=set(params)
    for b in blocks:
        for kind,obj in b.instructions:
            if kind=='stmt' and isinstance(obj,(Let,Assign)):
                defs[b.name].add(obj.name);allvars.add(obj.name)
    phis={n:[] for n in names}
    for var in sorted(allvars):
        work=[b.name for b in blocks if var in defs[b.name]]; placed=set()
        while work:
            n=work.pop()
            for y in frontier[n]-placed:
                phis[y].append(Phi(var,''));placed.add(y)
                if var not in defs[y]:work.append(y)
    kids={n:[] for n in names}
    for n,p in idom.items():
        if p is not None:kids[p].append(n)
    for children in kids.values():children.sort(key=block_order.__getitem__)
    stacks={v:[] for v in allvars}; counters={v:0 for v in allvars}; out={n:[] for n in names}
    for v in params:
        stacks[v].append(f'{v}.0')
    def fresh(v): counters[v]+=1; return f'{v}.{counters[v]}'
    def read(v): return stacks[v][-1] if stacks[v] else f'{v}.undef'
    def rename_expr(e):
        if isinstance(e,Var):return Var(read(e.name))
        if isinstance(e,Unary):return Unary(e.op,rename_expr(e.expr))
        if isinstance(e,Binary):return Binary(rename_expr(e.left),e.op,rename_expr(e.right))
        if isinstance(e,Call):return Call(e.name,[rename_expr(a) for a in e.args])
        return e
    def visit(n):
        pushed=[]
        for p in phis[n]: p.result=fresh(p.name);stacks[p.name].append(p.result);pushed.append(p.name)
        for kind,obj in next(b for b in blocks if b.name==n).instructions:
            if kind=='branch':out[n].append(SSAInstruction('branch',value=rename_expr(obj)));continue
            if isinstance(obj,Let):
                val=rename_expr(obj.expr);r=fresh(obj.name);stacks[obj.name].append(r);pushed.append(obj.name);out[n].append(SSAInstruction('let',r,val))
            elif isinstance(obj,Assign):
                val=rename_expr(obj.expr);r=fresh(obj.name);stacks[obj.name].append(r);pushed.append(obj.name);out[n].append(SSAInstruction('assign',r,val))
            elif isinstance(obj,Return):out[n].append(SSAInstruction('return',value=rename_expr(obj.expr)))
            elif isinstance(obj,ExprStmt):out[n].append(SSAInstruction('eval',value=rename_expr(obj.expr)))
        for succ in next(b for b in blocks if b.name==n).successors:
            for p in phis[succ]:p.incoming[n]=read(p.name)
        for child in kids[n]:visit(child)
        for v in reversed(pushed):stacks[v].pop()
    visit(entry)
    fn=SSAFunction(cfg,phis,out,dom,frontier); verify_ssa(fn);return fn

def verify_ssa(fn):
    defs={}; blockmap={b.name:b for b in fn.cfg.blocks}
    # Function parameters are the incoming definitions at the entry block.
    for ins in fn.instructions.values():
        for i in ins:
            if i.value is not None:
                for v in _expr_vars(i.value):
                    if v.endswith('.0') and v.rsplit('.',1)[0].isidentifier(): defs.setdefault(v, fn.cfg.entry.name)
    for b,ps in fn.phis.items():
        for p in ps:
            if len(p.incoming)!=len(blockmap[b].predecessors) or set(p.incoming)!=set(blockmap[b].predecessors): raise ValueError(f'invalid phi predecessors in {b}')
            if p.result in defs:raise ValueError(f'multiple definitions of {p.result}')
            defs[p.result]=b
    for b,ins in fn.instructions.items():
        for i in ins:
            if i.result:
                if i.result in defs:raise ValueError(f'multiple definitions of {i.result}')
                defs[i.result]=b
    def check_expr(e, useblock, allowed=None):
        for v in _expr_vars(e):
            if v.endswith('.undef'): continue
            if v not in defs: raise ValueError(f'use without definition: {v}')
            db=defs[v]
            if db!=useblock and db not in fn.dominators[useblock]:raise ValueError(f'{v} does not dominate use in {useblock}')
    for b,ps in fn.phis.items():
        for p in ps:
            for pred,v in p.incoming.items():
                if not v.endswith('.undef') and (v not in defs or (defs[v]!=pred and defs[v] not in fn.dominators[pred])):raise ValueError(f'invalid phi input {v} from {pred}')
    for b,ins in fn.instructions.items():
        for i in ins:check_expr(i.value,b)
    return True
