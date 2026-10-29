"""Small C-subset frontend using pycparser; not a complete C compiler."""
from __future__ import annotations
import re
from pycparser import c_parser, c_ast
from parser import (Program, Function, Number, Bool, Var, Unary, Binary, Call,
                    Let, Assign, Return, ExprStmt, If, While)

class CFrontendError(Exception):
    pass

_BINOPS = {
    '+': '+', '-': '-', '*': '*', '/': '/', '%': '%',
    '==': '==', '!=': '!=', '<': '<', '<=': '<=', '>': '>', '>=': '>=',
    '&&': '&&', '||': '||',
}

class CFrontend:
    """Translate a documented, deliberately small C subset to the prototype AST."""
    def parse(self, source: str) -> Program:
        # pycparser expects preprocessed input. This frontend intentionally accepts
        # printf as a builtin and strips include directives rather than preprocessing.
        source = re.sub(r'^\s*#\s*include[^\n]*', '', source, flags=re.M)
        source = re.sub(r'^\s*#\s*define[^\n]*', '', source, flags=re.M)
        try:
            tree = c_parser.CParser().parse(source)
            program = Program()
            for ext in tree.ext:
                if isinstance(ext, c_ast.FuncDef):
                    name = ext.decl.name
                    params = []
                    args = ext.decl.type.args
                    if args and args.params:
                        for p in args.params:
                            if isinstance(p, c_ast.EllipsisParam):
                                raise CFrontendError("Variadic functions are not supported")
                            # `int main(void)` is the standard spelling of no parameters.
                            if isinstance(p, c_ast.Typename) and isinstance(p.type, c_ast.TypeDecl) and isinstance(p.type.type, c_ast.IdentifierType) and p.type.type.names == ['void']:
                                continue
                            if not isinstance(p, c_ast.Decl) or not p.name:
                                raise CFrontendError("Only named function parameters are supported")
                            params.append(p.name)
                    body = self._compound(ext.body)
                    program.functions[name] = Function(name, params, body)
                elif isinstance(ext, c_ast.Decl):
                    raise CFrontendError("Global variables are not supported in this prototype")
                else:
                    raise CFrontendError(f"Unsupported top-level C construct: {type(ext).__name__}")
            if "main" not in program.functions:
                raise CFrontendError("C source must define int main(...)")
            program.statements.append(ExprStmt(Call("main", [])))
            return program
        except CFrontendError:
            raise
        except Exception as exc:
            raise CFrontendError(str(exc)) from exc

    def _compound(self, node):
        out = []
        for item in node.block_items or []:
            converted = self._stmt(item)
            if isinstance(converted, list):
                out.extend(converted)
            elif converted is not None:
                out.append(converted)
        return out

    def _stmt(self, n):
        if isinstance(n, c_ast.Compound):
            return self._compound(n)
        if isinstance(n, c_ast.DeclList):
            return [self._stmt(d) for d in n.decls]
        if isinstance(n, c_ast.Decl):
            if not isinstance(n.type, c_ast.TypeDecl):
                raise CFrontendError("Only scalar local declarations are supported")
            if n.init is None:
                value = Number(0)
            else:
                value = self._expr(n.init)
            return Let(n.name, value)
        if isinstance(n, c_ast.Assignment):
            if n.op != '=' or not isinstance(n.lvalue, c_ast.ID):
                raise CFrontendError("Only simple variable assignments using '=' are supported")
            return Assign(n.lvalue.name, self._expr(n.rvalue))
        if isinstance(n, c_ast.Return):
            return Return(self._expr(n.expr) if n.expr else Number(0))
        if isinstance(n, c_ast.If):
            then_body = self._as_list(self._stmt(n.iftrue))
            else_body = self._as_list(self._stmt(n.iffalse)) if n.iffalse else []
            return If(self._expr(n.cond), then_body, else_body)
        if isinstance(n, c_ast.While):
            return While(self._expr(n.cond), self._as_list(self._stmt(n.stmt)))
        if isinstance(n, c_ast.For):
            init = self._stmt(n.init) if n.init else None
            cond = self._expr(n.cond) if n.cond else Bool(True)
            nxt = self._stmt(n.next) if n.next else None
            body = self._as_list(self._stmt(n.stmt))
            if nxt is not None:
                body.extend(self._as_list(nxt))
            loop = While(cond, body)
            init_list = self._as_list(init)
            return init_list + [loop]
        if isinstance(n, c_ast.FuncCall):
            expr = self._expr(n)
            return ExprStmt(expr)
        if isinstance(n, c_ast.EmptyStatement):
            return None
        if isinstance(n, c_ast.UnaryOp) and n.op in ('p++', 'p--', '++', '--') and isinstance(n.expr, c_ast.ID):
            delta = 1 if '+' in n.op else -1
            return Assign(n.expr.name, Binary(Var(n.expr.name), '+', Number(delta)))
        raise CFrontendError(f"Unsupported statement: {type(n).__name__}")

    @staticmethod
    def _as_list(n):
        if n is None:
            return []
        return n if isinstance(n, list) else [n]

    def _expr(self, n):
        if isinstance(n, c_ast.Constant):
            if n.type in ('int', 'char'):
                raw = n.value
                try:
                    return Number(int(raw, 0))
                except ValueError:
                    return Number(int(raw.rstrip('uUlL'), 0))
            if n.type == 'string':
                return Call("__string_literal", [Number(0)])
            raise CFrontendError(f"Unsupported C constant type: {n.type}")
        if isinstance(n, c_ast.ID):
            return Var(n.name)
        if isinstance(n, c_ast.BinaryOp):
            if n.op not in _BINOPS:
                raise CFrontendError(f"Unsupported binary operator: {n.op}")
            # The toy runtime uses booleans for comparisons. Logical operators are
            # mapped to comparisons only when both operands are truth-valued.
            return Binary(self._expr(n.left), _BINOPS[n.op], self._expr(n.right))
        if isinstance(n, c_ast.UnaryOp):
            if n.op in ('-', '!'):
                return Unary(n.op, self._expr(n.expr))
            if n.op == '+':
                return self._expr(n.expr)
            if n.op in ('p++', 'p--', '++', '--') and isinstance(n.expr, c_ast.ID):
                delta = 1 if '+' in n.op else -1
                return Binary(Var(n.expr.name), '+', Number(delta))
            raise CFrontendError(f"Unsupported unary operator: {n.op}")
        if isinstance(n, c_ast.FuncCall):
            name = n.name.name if isinstance(n.name, c_ast.ID) else None
            if not name:
                raise CFrontendError("Indirect function calls are not supported")
            args = [self._expr(a) for a in (n.args.exprs if n.args else [])]
            if name == 'printf':
                # Common review-demo idiom: printf("%d\\n", value) -> print(value).
                if len(args) == 2 and isinstance(n.args.exprs[0], c_ast.Constant) and n.args.exprs[0].type == 'string':
                    return Call('print', [args[1]])
                if len(args) == 1:
                    return Call('print', args)
                raise CFrontendError("printf supports printf(\"%d\\n\", value) or one argument only")
            if name == 'puts':
                raise CFrontendError("puts/string output is not supported; use printf with an integer")
            return Call(name, args)
        if isinstance(n, c_ast.Cast):
            return self._expr(n.expr)
        raise CFrontendError(f"Unsupported expression: {type(n).__name__}")
