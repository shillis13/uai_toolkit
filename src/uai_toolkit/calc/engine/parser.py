"""Pratt (top-down operator-precedence) parser: tokens -> AST.

Grammar highlights:
  * precedence & associativity via binding powers; ``^`` is right-associative
    and binds tighter than unary minus, so ``-2^2 == -(2^2)``.
  * factorial ``!`` is a tight postfix operator.
  * implicit multiplication is inserted only for the safe adjacencies
    number->name (``2pi``), number->'(' (``2(3+4)``), and ')'->number/name/'('.
  * ``name(args)`` is a call; ``lambda(params, body)`` is an anonymous function.
  * a statement is ``target = value`` (variable or ``f(x)=...`` function) or a
    bare expression; statements are separated by ``;`` and the last is the value.
"""

from __future__ import annotations

from typing import List, Optional

from uai_toolkit.calc.engine.errors import ParseError
from uai_toolkit.calc.engine.tokenizer import Token, tokenize, T
from uai_toolkit.calc.engine import ast_nodes as A

# Left binding powers for infix/postfix operators (higher = tighter).
# Bitwise ops sit below arithmetic (C-like), among themselves: shift > and > xor > or.
_LBP = {
    T.PIPE: 6, T.XOR: 7, T.AMP: 8, T.LSHIFT: 9, T.RSHIFT: 9,
    T.PLUS: 10, T.MINUS: 10,
    T.STAR: 20, T.SLASH: 20, T.DSLASH: 20, T.PERCENT: 20,
    T.CARET: 40,
    T.BANG: 50,
}
_IMPLICIT_MUL_BP = 20   # same tier as '*'
_CALL_BP = 60           # a call binds tighter than arithmetic
_PREFIX_BP = 30         # unary +/- : between multiplicative and power
_RIGHT_ASSOC = {T.CARET}

# Tokens that can begin a new operand (used to detect implicit multiplication).
_OPERAND_START = {T.NUMBER, T.NAME, T.LPAREN}


class Parser:
    def __init__(self, tokens: List[Token], source: str) -> None:
        self.toks = tokens
        self.src = source
        self.i = 0

    # -- token helpers ------------------------------------------------------
    def peek(self) -> Token:
        return self.toks[self.i]

    def prev(self) -> Token:
        return self.toks[self.i - 1]

    def advance(self) -> Token:
        tok = self.toks[self.i]
        self.i += 1
        return tok

    def expect(self, ttype: str, what: str) -> Token:
        tok = self.peek()
        if tok.type != ttype:
            raise ParseError("expected {}".format(what), pos=tok.pos, source=self.src)
        return self.advance()

    # -- entry point --------------------------------------------------------
    def parse_program(self) -> A.Program:
        if self.peek().type == T.EOF:
            raise ParseError("empty expression", pos=0, source=self.src)
        statements = [self.parse_statement()]
        while self.peek().type == T.SEMI:
            self.advance()
            if self.peek().type == T.EOF:      # trailing ';' is harmless
                break
            statements.append(self.parse_statement())
        self.expect(T.EOF, "end of input")
        return A.Program(statements=statements, pos=0)

    def parse_statement(self) -> A.Node:
        expr = self.parse_expr(0)
        if self.peek().type == T.ASSIGN:
            eq = self.advance()
            value = self.parse_expr(0)
            return self._to_assign(expr, value, eq.pos)
        if self.peek().type == T.AS:
            kw = self.advance()
            base_tok = self.expect(T.NAME, "a base name after 'as' (hex/bin/oct/dec)")
            return A.AsBase(expr, str(base_tok.value).lower(), kw.pos)
        return expr

    def _to_assign(self, target: A.Node, value: A.Node, pos: int) -> A.Assign:
        # variable:  name = value
        if isinstance(target, A.Name):
            return A.Assign(name=target.name, params=None, value=value, pos=pos)
        # function:  f(p, q) = value   (parsed as Call(Name, [Name, ...]))
        if isinstance(target, A.Call) and isinstance(target.func, A.Name):
            params = []
            for arg in target.args:
                if not isinstance(arg, A.Name):
                    raise ParseError(
                        "function parameters must be plain names",
                        pos=arg.pos, source=self.src,
                    )
                params.append(arg.name)
            return A.Assign(name=target.func.name, params=params, value=value, pos=pos)
        raise ParseError("invalid assignment target", pos=target.pos, source=self.src)

    # -- expression (Pratt) -------------------------------------------------
    def parse_expr(self, min_bp: int) -> A.Node:
        left = self.nud()
        while True:
            tok = self.peek()
            # implicit multiplication (virtual infix) -------------------
            if self._implicit_mul_here(left, tok) and _IMPLICIT_MUL_BP > min_bp:
                right = self.parse_expr(_IMPLICIT_MUL_BP)
                left = A.BinOp(T.STAR, left, right, tok.pos)
                continue
            # function call ---------------------------------------------
            if tok.type == T.LPAREN and self._callable(left) and _CALL_BP > min_bp:
                left = self._parse_call(left)
                continue
            # real infix / postfix operators ----------------------------
            lbp = _LBP.get(tok.type)
            if lbp is None or lbp <= min_bp:
                break
            self.advance()
            if tok.type == T.BANG:
                left = A.Postfix(T.BANG, left, tok.pos)
            else:
                next_min = lbp - 1 if tok.type in _RIGHT_ASSOC else lbp
                right = self.parse_expr(next_min)
                left = A.BinOp(tok.type, left, right, tok.pos)
        return left

    def nud(self) -> A.Node:
        tok = self.advance()
        if tok.type == T.NUMBER:
            return A.Num(tok.value, tok.pos)
        if tok.type == T.NAME:
            return A.Name(tok.value, tok.pos)
        if tok.type == T.LAMBDA:
            return self._parse_lambda(tok.pos)
        if tok.type == T.LET:
            return self._parse_let(tok.pos)
        if tok.type in (T.MINUS, T.PLUS, T.TILDE):
            operand = self.parse_expr(_PREFIX_BP)
            return A.UnaryOp(tok.type, operand, tok.pos)
        if tok.type == T.LPAREN:
            inner = self.parse_expr(0)
            self.expect(T.RPAREN, "')'")
            return inner
        raise ParseError(
            "unexpected {}".format(_describe(tok)), pos=tok.pos, source=self.src
        )

    # -- sub-parsers --------------------------------------------------------
    def _parse_call(self, func: A.Node) -> A.Call:
        lp = self.expect(T.LPAREN, "'('")
        args: List[A.Node] = []
        if self.peek().type != T.RPAREN:
            args.append(self.parse_expr(0))
            while self.peek().type == T.COMMA:
                self.advance()
                args.append(self.parse_expr(0))
        self.expect(T.RPAREN, "')'")
        return A.Call(func, args, lp.pos)

    def _parse_let(self, pos: int) -> A.Let:
        bindings: List[A.Assign] = []
        while True:
            target = self.parse_expr(0)
            eq = self.expect(T.ASSIGN, "'=' in let binding")
            value = self.parse_expr(0)
            binding = self._to_assign(target, value, eq.pos)
            binding.local = True
            bindings.append(binding)
            if self.peek().type == T.COMMA:
                self.advance()
                continue
            break
        self.expect(T.COLON, "':' before the let body")
        body = self.parse_expr(0)
        return A.Let(bindings, body, pos)

    def _parse_lambda(self, pos: int) -> A.Lambda:
        self.expect(T.LPAREN, "'(' after lambda")
        items: List[A.Node] = [self.parse_expr(0)]
        while self.peek().type == T.COMMA:
            self.advance()
            items.append(self.parse_expr(0))
        self.expect(T.RPAREN, "')'")
        if len(items) < 2:
            raise ParseError(
                "lambda needs parameters and a body: lambda(x, body)",
                pos=pos, source=self.src,
            )
        *param_nodes, body = items
        params = []
        for p in param_nodes:
            if not isinstance(p, A.Name):
                raise ParseError(
                    "lambda parameters must be plain names", pos=p.pos, source=self.src
                )
            params.append(p.name)
        return A.Lambda(params, body, pos)

    # -- predicates ---------------------------------------------------------
    def _callable(self, left: A.Node) -> bool:
        # Syntactic callability: names, prior calls, and lambdas take '(' as a
        # call; numbers and arithmetic groups take '(' as implicit multiplication.
        return isinstance(left, (A.Name, A.Call, A.Lambda))

    def _implicit_mul_here(self, left: A.Node, tok: Token) -> bool:
        if tok.type not in _OPERAND_START:
            return False
        prev = self.prev()  # last token consumed to build `left`
        # number followed by a name or '(' :  2pi, 2(3+4)
        if prev.type == T.NUMBER and tok.type in (T.NAME, T.LPAREN):
            return True
        # ')' followed by a number, name, or '(' :  (1+2)3, (1+2)x, (1+2)(3)
        if prev.type == T.RPAREN and tok.type in (T.NUMBER, T.NAME, T.LPAREN):
            # '(' after ')' where left is callable is a call, not a product
            if tok.type == T.LPAREN and self._callable(left):
                return False
            return True
        return False


def _describe(tok: Token) -> str:
    if tok.type == T.EOF:
        return "end of input"
    if tok.type == T.NUMBER:
        return "number {}".format(tok.value)
    if tok.type == T.NAME:
        return "name '{}'".format(tok.value)
    return "'{}'".format(tok.value)


def parse(source: str) -> A.Program:
    """Tokenize and parse ``source`` into a :class:`~calc.engine.ast_nodes.Program`."""
    return Parser(tokenize(source), source).parse_program()
