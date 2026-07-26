"""Help content and colorization for `calc help [topic]` and the REPL `?`.

Coloring reuses the shared ``common_utils.lib_outputColors`` library (the
canonical zero-dependency color lib for ~/bin/python tools), which already
handles NO_COLOR / TERM=dumb / non-tty detection. If that package isn't
importable (e.g. calc shipped standalone), a no-op shim keeps help plain.
"""

from __future__ import annotations

import re
from typing import Optional

from uai_toolkit.calc.engine.builtins import BUILTINS, CONSTANTS

try:  # reuse the shared color library
    from uai_toolkit.common_utils.lib_outputColors import Colors
except Exception:  # pragma: no cover - standalone fallback
    class Colors:  # type: ignore[no-redef]
        RESET = BOLD = DIM = CYAN = GREEN = YELLOW = BLUE = MAGENTA = ""

        @classmethod
        def enabled(cls) -> bool:
            return False

        @classmethod
        def colorize(cls, text: str, *codes: str) -> str:
            return text


# --- colorization ----------------------------------------------------------

_HEADER_RE = re.compile(r"^[A-Z][A-Z0-9 &/()'\-]*$")


def _paint_inline(line: str) -> str:
    """Color a result marker ('-> …') green and a trailing '# …' comment dim."""
    hashpos = line.find("#")
    comment = ""
    if hashpos != -1:
        comment = Colors.colorize(line[hashpos:], Colors.DIM)
        line = line[:hashpos]
    m = re.search(r"->|=>", line)
    if m:
        line = line[:m.start()] + Colors.colorize(line[m.start():], Colors.GREEN)
    return line + comment


def _paint(text: str) -> str:
    if not Colors.enabled():
        return text
    out = []
    for line in text.split("\n"):
        stripped = line.strip()
        # section header (a whole non-indented line in caps)
        if stripped and not line[:1].isspace() and _HEADER_RE.match(stripped):
            out.append(Colors.colorize(line, Colors.BOLD, Colors.CYAN))
            continue
        # option row: "  -o, --out BASE   description"
        if stripped.startswith("-"):
            m = re.match(r"^(\s+)(.*?)(\s{2,})(.*)$", line)
            if m:
                out.append(m.group(1) + Colors.colorize(m.group(2), Colors.YELLOW)
                           + m.group(3) + _paint_inline(m.group(4)))
                continue
        # example/command row starting with the program name
        m = re.match(r"^(\s*)(calc|\./cli\.py)\b(.*)$", line)
        if m:
            out.append(m.group(1) + Colors.colorize(m.group(2), Colors.BLUE)
                       + _paint_inline(m.group(3)))
            continue
        out.append(_paint_inline(line))
    return "\n".join(out)


# --- content ---------------------------------------------------------------

USAGE = """\
calc — a fast command-line calculator

USAGE
  calc "EXPR"              evaluate an expression          calc "3 + 4*2"  -> 11
  calc EXPR...             bare args are joined            calc 3 + 4 \\* 2
  echo EXPR | calc         read from stdin (filter)        echo 2^10 | calc
  EXPR | calc "ans*10"     stdin value bound to ans/_
  calc                     interactive REPL (at a tty)
  ./cli.py "EXPR"          run directly (shebang)          # or: python3 -m calc

OPTIONS
  -o, --out BASE           output base: dec|hex|bin|oct    calc -o hex 255+1  -> 0x100
  --deg | --rad            angle mode for this call        calc --deg "sin(30)"  -> 0.5
  -p, --precision N        significant figures (floats)
  --full                   show full float precision
  -i, --repl               force the interactive REPL
  --examples               print worked examples
  -h, --help               this help
  --version                print version

NUMBERS
  decimal      42   3.14   .5   6.02e23
  grouping     1,234,567   12,345.67       # commas between 3-digit groups
  underscores  1_000_000
  bases in     0x1F   0b1010   0o17

OPERATORS
  + -           add, subtract
  * / // %      multiply, divide, floor-divide, modulo   (the word 'mod' = %)
  ^  or  **     power   (right associative; -2^2 = -4)
  !             factorial (postfix)
  & | ~ << >>   bitwise; the word 'xor' (^ is power, not xor)
  as            output base:   255 + 1 as hex  -> 0x100

EXPRESSIONS
  implicit mult   2pi   2(3+4)
  comments        5 # everything after # is ignored
  multi-step      r=5; area=pi*r^2; area   -> 78.54
  functions       f(x) = x^2 + 1   then   f(5)   -> 26
  lambda / let    (lambda(x, x*x))(4)      let a=2, b=3 : a*b

MANAGE DEFINITIONS   (persist to ~/.config/calc/calcrc)
  calc def "f(x)=x^2+1"    save a function/constant
  calc list                list saved definitions (numbered)
  calc show f | show 2     show one (by name or list-number)
  calc del  f | del  2     remove one
  calc clear [--yes]       remove all
  calc set angle deg       persist a default (angle/base/precision/full)
  calc edit | calc path    open / locate calcrc

MORE
  calc help functions      the full function catalog
  calc help examples       worked examples (or: calc --examples)
  calc help sin            help on one function or constant"""


EXAMPLES = """\
EXAMPLES

BASICS
  calc "3 + 4 * 2"              -> 11
  calc "(3 + 4) * 2"           -> 14
  calc 3 + 4 \\* 2             -> 11      # bare args (escape * from the shell)
  calc "2^10"                 -> 1024
  calc "-2^2"                 -> -4       # power binds tighter than unary minus
  calc "7 // 2"               -> 3        # floor division
  calc "-7 % 3"               -> 2        # floored modulo
  calc "5!"                   -> 120      # factorial

BIG NUMBERS WITH COMMAS
  calc "1,234,567 + 1"         -> 1234568
  calc "12,345.67 * 2"         -> 24691.34

LEGIBLE OUTPUT
  calc "0.1 + 0.2"             -> 0.3     # float noise cleaned up
  calc "1/3"                   -> 0.333333333333
  calc "10/2"                 -> 5        # exact stays an integer
  calc --full "1/3"           -> 0.3333333333333333

FUNCTIONS & CONSTANTS
  calc "sqrt(16)"             -> 4
  calc "log(1024, 2)"         -> 10
  calc "gcd(24, 36)"          -> 12
  calc "round(3.14159, 2)"    -> 3.14
  calc "2*pi"                 -> 6.28318530718

ANGLE MODE
  calc --deg "sin(30)"        -> 0.5
  calc --deg "asin(0.5)"      -> 30
  calc "sin(pi/2)"            -> 1        # default is radians

BASES (IN AND OUT)
  calc "0xFF + 1"             -> 256
  calc -o hex "255 + 1"       -> 0x100
  calc "255 as bin"           -> 0b11111111
  calc "0b1010 | 0b0101"      -> 15       # bitwise or
  calc "1 << 8"               -> 256
  calc "255 xor 15"           -> 240

STDIN & PIPES
  echo "2^10" | calc          -> 1024
  printf '2+2\\n2^8\\n' | calc  -> 4, then 256   # one result per line
  echo 40 | calc "ans / 8"     -> 5      # the stdin value is bound to ans/_

MULTI-STEP & DEFINITIONS
  calc "r = 5; pi*r^2"        -> 78.5398163397
  calc "let a=3, b=4 : hypot(a,b)"   -> 5
  calc def "f(x) = x^2 + 1"   # save it...
  calc "f(9)"                 -> 82      # ...then use it any time
  calc list                   # review what's saved

$ans ACROSS SHELL COMMANDS
  eval "$(calc shell-init bash)"    # add to ~/.bashrc (zsh/fish also supported)
  calc 2+2                    -> 4       # also exports $ans=4
  calc "$ans * 10"            -> 40

INTERACTIVE
  calc                        # REPL: type expressions, ? for help, quit to exit"""


_FN_DESC = {
    "sqrt": "square root", "cbrt": "cube root", "abs": "absolute value",
    "sin": "sine", "cos": "cosine", "tan": "tangent",
    "asin": "inverse sine", "acos": "inverse cosine", "atan": "inverse tangent",
    "ln": "natural log", "log": "log (natural, or given base)",
    "log2": "base-2 log", "log10": "base-10 log", "exp": "e to the x",
    "floor": "round down", "ceil": "round up",
    "round": "round half away from zero", "sign": "-1, 0, or 1",
    "min": "smallest", "max": "largest", "gcd": "greatest common divisor",
    "lcm": "least common multiple", "factorial": "n! (also postfix !)",
    "hypot": "sqrt(x^2 + y^2)",
}


def _sig(name: str) -> str:
    lo, hi, _ = BUILTINS[name]
    if name == "log":
        return "log(x[, base])"
    if name == "round":
        return "round(x[, n])"
    if hi is None:
        return "{}(…)".format(name)
    if lo == hi == 1:
        return "{}(x)".format(name)
    if lo == hi == 2:
        return "{}(x, y)".format(name)
    return "{}(…)".format(name)


def _functions_list() -> str:
    lines = [Colors.colorize("FUNCTIONS", Colors.BOLD, Colors.CYAN)
             if Colors.enabled() else "FUNCTIONS"]
    for name in sorted(BUILTINS):
        sig = _sig(name)
        desc = _FN_DESC.get(name, "")
        sig_c = Colors.colorize(sig, Colors.GREEN) if Colors.enabled() else sig
        pad = " " * max(1, 18 - len(sig))
        lines.append("  {}{}{}".format(sig_c, pad, desc))
    lines.append("")
    head = Colors.colorize("CONSTANTS", Colors.BOLD, Colors.CYAN) \
        if Colors.enabled() else "CONSTANTS"
    lines.append(head)
    consts = ", ".join(sorted(CONSTANTS))
    lines.append("  " + (Colors.colorize(consts, Colors.GREEN)
                         if Colors.enabled() else consts))
    return "\n".join(lines)


def help_text(topic: Optional[str] = None) -> str:
    if not topic:
        return _paint(USAGE)
    t = topic.lower()
    if t in ("examples", "example", "ex"):
        return _paint(EXAMPLES)
    if t in ("functions", "funcs", "fn"):
        return _functions_list()
    if t in BUILTINS:
        lo, hi, _ = BUILTINS[t]
        arity = "1" if lo == hi else ("{}+".format(lo) if hi is None
                                      else "{}-{}".format(lo, hi))
        name = Colors.colorize(_sig(t), Colors.GREEN) if Colors.enabled() else _sig(t)
        return "{} — {}  (arguments: {})".format(name, _FN_DESC.get(t, ""), arity)
    if t in CONSTANTS:
        name = Colors.colorize(t, Colors.GREEN) if Colors.enabled() else t
        return "{} = {}".format(name, CONSTANTS[t])
    return "no help topic '{}'. Try:  calc help functions   or   calc help examples".format(topic)
