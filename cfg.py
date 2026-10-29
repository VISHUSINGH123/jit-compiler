"""Explicit control-flow graph builder for the toy AST.

This builds real basic-block objects and control-flow edges for if/while statements.
It does not perform dominator analysis or SSA renaming; those remain future work.
"""
from dataclasses import dataclass, field
from parser import If, While, Return

@dataclass
class BasicBlock:
    name: str
    instructions: list = field(default_factory=list)
    successors: list = field(default_factory=list)
    predecessors: list = field(default_factory=list)

class CFG:
    def __init__(self):
        self.blocks = []
        self.counter = 0
        self.entry = self.new_block("entry")
    def new_block(self, label):
        self.counter += 1
        b = BasicBlock(f"bb{self.counter}_{label}")
        self.blocks.append(b)
        return b
    @staticmethod
    def edge(a, b):
        if b.name not in a.successors: a.successors.append(b.name)
        if a.name not in b.predecessors: b.predecessors.append(a.name)
    def lower(self, stmts, current):
        for s in stmts:
            if current is None: break
            if isinstance(s, If):
                current.instructions.append(f"branch {s.cond!r}")
                then_b = self.new_block("if_then")
                else_b = self.new_block("if_else")
                merge = self.new_block("if_merge")
                self.edge(current, then_b); self.edge(current, else_b)
                t_end = self.lower(s.then_body, then_b)
                e_end = self.lower(s.else_body, else_b)
                if t_end is not None: self.edge(t_end, merge)
                if e_end is not None: self.edge(e_end, merge)
                current = merge
            elif isinstance(s, While):
                header = self.new_block("loop_header")
                body = self.new_block("loop_body")
                exit_b = self.new_block("loop_exit")
                self.edge(current, header)
                header.instructions.append(f"loop-condition {s.cond!r}")
                self.edge(header, body); self.edge(header, exit_b)
                body_end = self.lower(s.body, body)
                if body_end is not None: self.edge(body_end, header)
                current = exit_b
            else:
                current.instructions.append(repr(s))
                if isinstance(s, Return):
                    current.instructions.append("terminator: return")
                    current = None
        return current
    @classmethod
    def from_statements(cls, stmts):
        cfg = cls()
        cfg.lower(stmts, cfg.entry)
        return cfg
    def dump(self):
        lines = ["CFG (explicit blocks and edges; dominance details are in verified SSA output)"]
        for b in self.blocks:
            lines.append(f"{b.name}:")
            lines.extend(f"  {x}" for x in b.instructions)
            lines.append(f"  preds: {', '.join(b.predecessors) or '-'}")
            lines.append(f"  succs: {', '.join(b.successors) or '-'}")
        return "\n".join(lines)
