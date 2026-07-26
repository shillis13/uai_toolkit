# calc

A fast, intuitive, cross-platform command-line calculator. Zero-dependency
engine; the interactive REPL optionally uses `prompt_toolkit`.

## Install

```bash
pip install -e ~/bin/python              # exposes the `calc` command
pip install -e '~/bin/python[calc-repl]' # + enhanced REPL (prompt_toolkit)
```

Or run without installing: `python3 -m calc "2+2"` (from `~/bin/python/src`).

## Use

```bash
calc "3 + 4*2"            # 11
calc 3 + 4 \* 2          # bare args are joined
echo "2^10" | calc        # 1024   (reads stdin)
calc < formulas.txt       # one result per line
echo 40 | calc "ans/8"    # 5      (stdin value bound to ans/_)
calc -o hex "255 + 1"     # 0x100
calc --deg "sin(30)"      # 0.5
calc                      # interactive REPL (at a terminal)
calc --examples           # a full page of worked examples
./calc/cli.py "2+2"       # runs directly (shebang; no install needed)
```

Colorized `--help` and `--examples` (auto-plain when piped or under `NO_COLOR`).

### Expressions

- Arithmetic `+ - * / // %`, power `^` (or `**`), factorial `!`.
- Numbers accept thousands commas: `1,234,567`, `12,345.67`. (Inside a call,
  a comma with no following space groups digits — `f(1,234)` is `f(1234)`;
  write `f(1, 234)` for two arguments.)
- Bitwise (integers) `& | ~ << >>` and the word `xor` (`^` is power).
- Bases in: `0x1F 0b1010 0o17`; out: `255 as hex`, or `-o hex`, or `calc set base hex`.
- Implicit multiplication: `2pi`, `2(3+4)`. Comments: `5 # note`.
- Multi-step: `r=5; area=pi*r^2; area`.
- Functions: `f(x) = x^2 + 1` then `f(5)`. Lambda/let:
  `(lambda(x, x*x))(4)`, `let a=2, b=3 : a*b`.
- `-2^2 = -4` (power binds tighter than unary minus). `round` is half-away-from-zero.
  `%` / `//` use floored (Python) sign conventions.

### Saved definitions (persist to `~/.config/calc/calcrc`)

```bash
calc def "f(x)=x^2+1"    # save
calc list                # list (numbered)
calc show f | show 2     # show one (by name or list-number)
calc del  f | del  2     # remove one
calc clear [--yes]       # remove all
calc set angle deg       # persist a default (angle/base/precision/full)
calc edit | calc path    # open / locate calcrc
calc help [topic]        # help, or `calc help functions`
```

Bare definitions on the command line (`calc "c = 5"`) are **ephemeral** — they
never write to disk. Use `calc def` to persist.

### `$ans` in your shell

`ans`/`_` work inside a pipe or stream automatically. To carry `$ans` across
separate shell commands, source the wrapper:

```bash
eval "$(calc shell-init bash)"   # or zsh; fish: `calc shell-init fish | source`
calc 2+2        # 4   (also sets $ans=4 in this shell)
calc "$ans*10"  # 40
```

See `docs/2026-07-10-calc-cli-design.md` for the full design.
