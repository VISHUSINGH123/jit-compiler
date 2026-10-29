from dataclasses import dataclass

@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    line: int
    column: int

KEYWORDS = {"fn", "let", "return", "if", "else", "while", "true", "false"}

class LexerError(Exception):
    pass

class Lexer:
    def __init__(self, source: str):
        self.source = source
        self.i = 0
        self.line = 1
        self.col = 1

    def _peek(self, n=0):
        j = self.i + n
        return self.source[j] if j < len(self.source) else ""

    def _advance(self):
        ch = self._peek()
        if ch:
            self.i += 1
            if ch == "\n":
                self.line += 1
                self.col = 1
            else:
                self.col += 1
        return ch

    def tokenize(self):
        out = []
        while self._peek():
            ch = self._peek()
            if ch.isspace():
                self._advance()
                continue
            if ch == "/" and self._peek(1) == "/":
                while self._peek() and self._peek() != "\n":
                    self._advance()
                continue
            line, col = self.line, self.col
            if ch.isalpha() or ch == "_":
                s = ""
                while self._peek().isalnum() or self._peek() == "_":
                    s += self._advance()
                out.append(Token("KW" if s in KEYWORDS else "IDENT", s, line, col))
                continue
            if ch.isdigit():
                s = ""
                while self._peek().isdigit():
                    s += self._advance()
                out.append(Token("NUMBER", s, line, col))
                continue
            two = ch + self._peek(1)
            if two in ("==", "!=", "<=", ">="):
                self._advance(); self._advance()
                out.append(Token("OP", two, line, col))
                continue
            if ch in "+-*/%<>=!":
                self._advance()
                out.append(Token("OP", ch, line, col))
                continue
            if ch in "(){};,": 
                self._advance()
                out.append(Token(ch, ch, line, col))
                continue
            raise LexerError(f"Unexpected character {ch!r} at {line}:{col}")
        out.append(Token("EOF", "", self.line, self.col))
        return out
