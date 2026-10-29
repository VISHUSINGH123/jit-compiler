"""Readable SSA-style IR view for the prototype.

This is deliberately an educational approximation, not a full SSA constructor:
phi-like merge annotations are emitted for assignments that appear in both arms
of an if statement. Dominance-frontier placement and variable renaming are TODOs.
"""
from parser import *

class IRPrinter:
    def __init__(self):
        self.lines = []
        self.temp = 0
        self.block = 0
    def t(self):
        self.temp += 1; return f"%{self.temp}"
    def new_block(self, label):
        self.block += 1
        self.lines.append(f"bb{self.block}_{label}:")
    def expr(self, e):
        if isinstance(e, Number): return str(e.value)
        if isinstance(e, Bool): return str(e.value).lower()
        if isinstance(e, Var): return e.name
        if isinstance(e, Call):
            args = ", ".join(self.expr(a) for a in e.args)
            x = self.t(); self.lines.append(f"  {x} = call @{e.name}({args})"); return x
        if isinstance(e, Unary):
            x=self.t(); self.lines.append(f"  {x} = {e.op}{self.expr(e.expr)}"); return x
        if isinstance(e, Binary):
            a=self.expr(e.left); b=self.expr(e.right); x=self.t()
            self.lines.append(f"  {x} = {e.op} {a}, {b}"); return x
        return "<?>"
    def stmt(self, s):
        if isinstance(s, Let):
            self.lines.append(f"  {s.name}.1 = {self.expr(s.expr)}")
        elif isinstance(s, Assign):
            self.lines.append(f"  {s.name}.next = {self.expr(s.expr)}")
        elif isinstance(s, Return):
            self.lines.append(f"  ret {self.expr(s.expr)}")
        elif isinstance(s, ExprStmt):
            self.lines.append(f"  eval {self.expr(s.expr)}")
        elif isinstance(s, If):
            cond=self.expr(s.cond)
            self.lines.append(f"  br {cond}, then, else")
            self.new_block("then")
            for x in s.then_body: self.stmt(x)
            self.new_block("else")
            for x in s.else_body: self.stmt(x)
            self.new_block("merge")
            # Explicitly label this as an illustrative phi, not algorithmically verified SSA.
            names = sorted({x.name for x in s.then_body+s.else_body if isinstance(x,(Let,Assign))})
            for n in names:
                self.lines.append(f"  {n}.merge = phi({n}.then, {n}.else) ; illustrative")
        elif isinstance(s, While):
            self.new_block("loop_header")
            self.lines.append(f"  loop_cond {self.expr(s.cond)}")
            for x in s.body: self.stmt(x)
            self.lines.append("  br loop_header")
    def program(self, p):
        for f in p.functions.values():
            self.lines.append(f"function @{f.name}({', '.join(f.params)})")
            self.new_block(f.name)
            for s in f.body: self.stmt(s)
        return "\n".join(self.lines)
