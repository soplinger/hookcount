# Hookcount

**Offline crochet round-pattern checker.** Write your pattern as plain text, one round per line. Hookcount expands the repeats, checks every round against its stitch-count bracket and against the round before it, and then tells you the shape, the yarn and the time, and gives you a printable checklist.

It is a single Python 3 file using only the standard library. It makes no network calls and needs no account.

## Features

- **Round parser** for `R<n>: stitches [count]` lines, with `#` comments and blank lines ignored.
- **Repeat groups** such as `(sc2, inc) x6`, with stitch counts inside them.
- **Count suffixes** such as `sc6` or `dec3`, so you don't have to write six `sc`s.
- **Bracket check**: each round's produced stitches must match its `[count]`.
- **Continuity check**: each round must work into exactly the stitches the round before it made.
- **Magic ring rule**: `MR` is only valid at the start of R1.
- **Round sequence check**: rounds must be numbered 1, 2, 3 with no gaps.
- **Line and column errors** in the form `file:line:col: error: message`, so editors can jump to them.
- **Lint warnings** for a missing `[count]` and for a round that more than doubles the stitches (often a missed repeat).
- **Shape classification**: flat, increasing, decreasing or mixed, with the mean percentage increase per round.
- **Round table** showing consumed, produced and net stitches for each round.
- **Yarn estimate** in metres, scaled by stitch type and a base length you set.
- **Work-time estimate** from a stitches-per-minute setting.
- **Working checklist** in Markdown, one tick box per round.
- **JSON output** for `check` and `summary`, for scripts and dashboards.
- **CI exit codes**: `0` pass, `1` errors (or warnings under `--strict`), `2` file or usage problems.

## Quick start

The repository includes a worked beanie pattern in `examples/beanie.txt`:

```text
R1: MR, sc6 [6]
R2: inc6 [12]
R3: (sc, inc) x6 [18]
R4: (sc2, inc) x6 [24]
R5: sc24 [24]          # straight section
R6: (sc2, dec) x6 [18]
R7: sc18 [18]
R8: (sc1, dec) x6 [12]
R9: dec6 [6]
```

Check it, summarise it and print a checklist:

```sh
python3 hookcount.py check examples/beanie.txt
python3 hookcount.py summary examples/beanie.txt --base-cm 3.2 --spm 35
python3 hookcount.py checklist examples/beanie.txt > beanie-checklist.md
```

`examples/beanie_broken.txt` has a wrong bracket, a short repeat and a skipped round number, so you can see the errors Hookcount reports:

```sh
python3 hookcount.py check examples/beanie_broken.txt
```

## Pattern syntax

| Token | Consumes | Produces | Notes |
| --- | --- | --- | --- |
| `MR` | 0 | 0 | Magic ring. Only valid in R1. |
| `sc`, `hdc`, `dc`, `tr`, `slst` | 1 | 1 | `slst` is the slip stitch. |
| `inc` | 1 | 2 | Increase. |
| `dec` | 2 | 1 | Decrease. |
| `invdec` | 3 | 1 | Invisible decrease. |
| `sk` | 1 | 0 | Skip a stitch. |
| `ch` | 0 | 0 | Chain. Not counted as a stitch. |

Write `sc6` for six single crochets, and `(sc2, dec) x6` to repeat a group six times. Groups do not nest. Put a `[count]` at the end of each line so Hookcount can check it. Lines that start with `#`, or have a `#` after the code, are comments.

## How to run

Needs Python 3.8 or newer. Run these from the project directory:

```sh
python3 hookcount.py check PATTERN [--strict] [--json]
python3 hookcount.py summary PATTERN [--base-cm CM] [--spm N] [--json]
python3 hookcount.py checklist PATTERN
```

- `check` lists every error and warning. `--strict` makes warnings fail the run.
- `summary` refuses to estimate a pattern that still has errors.
- `--base-cm` is the yarn used by one single crochet, in centimetres (default 3.0). The estimate is only a guide, so swatch to confirm it.
- `--spm` is the worked stitches per minute (default 30).

### CI

Run `check --strict` in your pipeline. It exits `1` when a pattern has errors or warnings, so a bad pattern can't be merged.

## How to test

The tests use the standard `unittest` module and work with pytest as well:

```sh
python3 -m unittest discover -s tests -v
python3 -m pytest -q
```

They cover parsing, repeat expansion, bracket and continuity errors, the magic ring rule, shape and estimate maths, the checklist, and the command-line exit codes.

## Limitations

- Chains are not counted as stitches, so round 1 must start with `MR` (or with stitches that a chain-free start produces).
- Nested groups, front and back post stitches, and stitch names with spaces such as `sl st` are not supported. Use `slst`.
- Yarn and time figures are rough estimates, not measurements.

## Layout

```text
hookcount.py                 the tool (parser, checks, estimates, CLI)
examples/beanie.txt          a valid worked pattern
examples/beanie_broken.txt   the same pattern with deliberate mistakes
tests/test_hookcount.py      unit and CLI tests
conftest.py                  empty marker so pytest uses this folder as the root
```
