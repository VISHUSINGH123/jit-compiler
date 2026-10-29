from dataclasses import dataclass, field
from lexer import Lexer, Token

class ParseError(Exception):
    pass

@dataclass
class Number: value: int
@dataclass
class Bool: value: bool
@dataclass
class Var: name: str
@dataclass
class Unary: op: str; expr: object
@dataclass
class Binary: left: object; op: str; right: object
@dataclass
class Call: name: str; args: list
@dataclass
class Let: name: str; expr: object
@dataclass
class Assign: name: str; expr: object
@dataclass
class Return: expr: object
@dataclass
class ExprStmt: expr: object
@dataclass
class If: cond: object; then_body: list; else_body: list
@dataclass
class While: cond: object; body: list
@dataclass
class Function: name: str; params: list; body: list
@dataclass
class Program: functions: dict = field(default_factory=dict); statements: list = field(default_factory=list)

PRECEDENCE = {"==":1, "!=":1, "<":2, "<=":2, ">":2, ">=":2,
              "+":3, "-":3, "*":4, "/":4, "%":4}

class Parser:
    def __init__(self, source):
        self.tokens = Lexer(source).tokenize()
        self.i = 0

    def cur(self): return self.tokens[self.i]
    def at(self, kind, value=None):
        t = self.cur()
        return t.kind == kind and (value is None or t.value == value)
    def take(self):
        t = self.cur(); self.i += 1; return t
    def expect(self, kind, value=None):
        if not self.at(kind, value):
            t = self.cur()
            raise ParseError(f"Expected {value or kind}, got {t.value or t.kind} at {t.line}:{t.column}")
        return self.take()

    def parse(self):
        p = Program()
        while not self.at("EOF"):
            if self.at("KW", "fn"):
                f = self.function()
                if f.name in p.functions: raise ParseError(f"Duplicate function {f.name}")
                p.functions[f.name] = f
            else:
                p.statements.append(self.statement())
        return p

    def function(self):
        self.expect("KW", "fn")
        name = self.expect("IDENT").value
        self.expect("("); params = []
        if not self.at(")"):
            params.append(self.expect("IDENT").value)
            while self.at(","):
                self.take(); params.append(self.expect("IDENT").value)
        self.expect(")"); self.expect("{")
        body = self.block_until("}")
        self.expect("}")
        return Function(name, params, body)

    def block_until(self, end):
        body = []
        while not self.at(end) and not self.at("EOF"):
            body.append(self.statement())
        return body

    def statement(self):
        if self.at("KW", "let"):
            self.take(); name = self.expect("IDENT").value
            self.expect("OP", "="); expr = self.expression(); self.expect(";")
            return Let(name, expr)
        if self.at("KW", "return"):
            self.take(); expr = self.expression(); self.expect(";")
            return Return(expr)
        if self.at("KW", "if"):
            self.take(); self.expect("("); cond = self.expression(); self.expect(")")
            self.expect("{"); tb = self.block_until("}"); self.expect("}")
            eb = []
            if self.at("KW", "else"):
                self.take(); self.expect("{"); eb = self.block_until("}"); self.expect("}")
            return If(cond, tb, eb)
        if self.at("KW", "while"):
            self.take(); self.expect("("); cond = self.expression(); self.expect(")")
            self.expect("{"); body = self.block_until("}"); self.expect("}")
            return While(cond, body)
        if self.at("IDENT") and self.tokens[self.i+1].kind == "OP" and self.tokens[self.i+1].value == "=":
            name = self.take().value; self.take(); expr = self.expression(); self.expect(";")
            return Assign(name, expr)
        expr = self.expression(); self.expect(";")
        return ExprStmt(expr)

    def expression(self, min_prec=0):
        if self.at("OP") and self.cur().value in ("-", "!"):
            op = self.take().value
            left = Unary(op, self.expression(5))
        elif self.at("NUMBER"):
            left = Number(int(self.take().value))
        elif self.at("KW", "true") or self.at("KW", "false"):
            left = Bool(self.take().value == "true")
        elif self.at("IDENT"):
            name = self.take().value
            if self.at("("):
                self.take(); args = []
                if not self.at(")"):
                    args.append(self.expression())
                    while self.at(","):
                        self.take(); args.append(self.expression())
                self.expect(")")
                left = Call(name, args)
            else:
                left = Var(name)
        elif self.at("("):
            self.take(); left = self.expression(); self.expect(")")
        else:
            t = self.cur()
            raise ParseError(f"Expected expression, got {t.value or t.kind} at {t.line}:{t.column}")
        while self.at("OP") and self.cur().value in PRECEDENCE:
            op = self.cur().value; prec = PRECEDENCE[op]
            if prec < min_prec: break
            self.take()
            right = self.expression(prec + 1)
            left = Binary(left, op, right)
        return left
