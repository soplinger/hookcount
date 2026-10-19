#!/usr/bin/env python3
"""Hookcount: offline crochet round-pattern checker.

Reads a plain-text round pattern, expands repeat groups, checks every
round's stitch count against its [bracket] and against the round before,
and reports shape, yarn and time estimates plus a working checklist.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass

# stitch name -> (stitches consumed from the round below, stitches produced)
STITCHES = {
    "sc": (1, 1),
    "hdc": (1, 1),
    "dc": (1, 1),
    "tr": (1, 1),
    "slst": (1, 1),
    "inc": (1, 2),
    "dec": (2, 1),
    "invdec": (3, 1),
    "sk": (1, 0),
    "ch": (0, 0),
    "mr": (0, 0),
}

# Relative yarn used per stitch, in multiples of the base length (sc = 1.0).
YARN_FACTOR = {
    "sc": 1.0,
    "hdc": 1.1,
    "dc": 1.3,
    "tr": 1.6,
    "slst": 0.4,
    "inc": 2.0,
    "dec": 1.0,
    "invdec": 1.0,
    "sk": 0.0,
    "ch": 0.7,
    "mr": 0.0,
}

# Chains and the magic ring are not worked stitches, so they take no time.
NOT_WORKED = ("ch", "mr")

ROUND_RE = re.compile(r"^\s*R(\d+)\s*:(.*)$", re.IGNORECASE)
BRACKET_RE = re.compile(r"\[(\d+)\]\s*$")
TOKEN_RE = re.compile(r"^([a-z]+)(\d*)$", re.IGNORECASE)
ITEM_RE = re.compile(r"\s*(?:\([^()]*\)\s*[xX]\d+|[^,\s][^,]*)")
GROUP_RE = re.compile(r"^\((.*)\)\s*[xX](\d+)$")
TOKEN_LIST_RE = re.compile(r"[^,]+")


@dataclass
class Issue:
    line: int
    col: int
    severity: str  # "error" or "warning"
    message: str


@dataclass
class Round:
    number: int
    line: int
    body: str
    stitches: list
    consumed: int
    produced: int
    bracket: int | None


def _read_token(tok, col, line, issues):
    """Turn one token such as 'sc', 'sc6' or 'dec2' into stitch names."""
    if not tok:
        issues.append(Issue(line, col, "error", "empty stitch slot"))
        return []
    m = TOKEN_RE.match(tok)
    name = m.group(1).lower() if m else ""
    if name not in STITCHES:
        issues.append(Issue(line, col, "error", f"unknown stitch '{tok}'"))
        return []
    count = int(m.group(2)) if m.group(2) else 1
    if count < 1:
        issues.append(Issue(line, col, "error", f"stitch count must be at least 1 in '{tok}'"))
        return []
    return [name] * count


def _expand_body(body, col0, line, issues):
    """Expand a round body such as 'MR, sc6, (sc, inc) x6' into stitch names."""
    names = []
    for m in ITEM_RE.finditer(body):
        raw = m.group(0)
        text = raw.strip()
        col = col0 + m.start() + (len(raw) - len(raw.lstrip()))
        group = GROUP_RE.match(text)
        if not group:
            names.extend(_read_token(text, col, line, issues))
            continue
        inner, repeat = group.group(1), int(group.group(2))
        if repeat < 1:
            issues.append(Issue(line, col, "error", "group repeat must be at least 1"))
            continue
        inner_names = []
        for tm in TOKEN_LIST_RE.finditer(inner):
            piece = tm.group(0)
            tok = piece.strip()
            tcol = col + 1 + tm.start() + (len(piece) - len(piece.lstrip()))
            inner_names.extend(_read_token(tok, tcol, line, issues))
        if not inner_names:
            issues.append(Issue(line, col, "error", "group has no stitches"))
            continue
        names.extend(inner_names * repeat)
    return names


def parse_pattern(text):
    """Parse pattern text into (rounds, issues). Comments start with '#'."""
    rounds, issues = [], []
    expected = 1
    for lineno, raw in enumerate(text.splitlines(), start=1):
        code = raw.split("#", 1)[0]
        if not code.strip():
            continue
        m = ROUND_RE.match(code)
        if not m:
            issues.append(Issue(lineno, 1, "error", "expected 'R<n>: stitches [count]'"))
            continue
        number = int(m.group(1))
        body = m.group(2)
        body_col = m.start(2) + 1
        bracket_m = BRACKET_RE.search(body)
        body_text = body[: bracket_m.start()] if bracket_m else body
        bracket = int(bracket_m.group(1)) if bracket_m else None
        bracket_col = body_col + bracket_m.start() if bracket_m else body_col

        if number != expected:
            issues.append(Issue(lineno, 1, "error", f"expected R{expected}, found R{number}"))
        expected = number + 1

        if not body_text.strip():
            issues.append(Issue(lineno, body_col, "error", f"R{number} has no stitches"))
            continue

        stitches = _expand_body(body_text, body_col, lineno, issues)
        if "mr" in stitches and number != 1:
            issues.append(Issue(lineno, body_col, "error", "magic ring is only valid in R1"))
        consumed = sum(STITCHES[s][0] for s in stitches)
        produced = sum(STITCHES[s][1] for s in stitches)
        prev = rounds[-1] if rounds else None

        if prev is not None and consumed != prev.produced:
            issues.append(Issue(
                lineno, body_col, "error",
                f"R{number} works into {consumed} stitches but R{prev.number} made {prev.produced}",
            ))
        if bracket is None:
            issues.append(Issue(lineno, body_col, "warning", f"R{number} has no [count] to check"))
        elif bracket != produced:
            issues.append(Issue(
                lineno, bracket_col, "error",
                f"R{number} makes {produced} stitches but the bracket says [{bracket}]",
            ))
        if prev is not None and prev.produced and produced > 2 * prev.produced:
            issues.append(Issue(
                lineno, body_col, "warning",
                f"R{number} more than doubles the stitches ({prev.produced} to {produced}); check for a missed repeat",
            ))

        rounds.append(Round(number, lineno, body_text.strip(), stitches, consumed, produced, bracket))

    if not rounds and not issues:
        issues.append(Issue(1, 1, "error", "no rounds found"))
    return rounds, issues


def shape_of(rounds):
    """Classify the shaping from the stitch change in each round after R1."""
    nets = [r.produced - r.consumed for r in rounds[1:]]
    if not nets or all(n == 0 for n in nets):
        return "flat"
    ups = any(n > 0 for n in nets)
    downs = any(n < 0 for n in nets)
    if ups and downs:
        return "mixed"
    return "increasing" if ups else "decreasing"


def increase_pct(rounds):
    """Mean percentage growth over the rounds that add stitches, or None."""
    rates = [
        (r.produced - r.consumed) / r.consumed
        for r in rounds[1:]
        if r.produced > r.consumed and r.consumed
    ]
    return round(100 * sum(rates) / len(rates), 1) if rates else None


def summarise(rounds, base_cm=3.0, spm=30.0):
    """Build the data behind the summary: round table, shape and estimates."""
    table = []
    for i, r in enumerate(rounds):
        net = None if i == 0 else r.produced - r.consumed
        table.append({
            "number": r.number,
            "consumed": r.consumed,
            "produced": r.produced,
            "net": net,
            "bracket": r.bracket,
        })
    all_stitches = [s for r in rounds for s in r.stitches]
    total_cm = sum(YARN_FACTOR[s] for s in all_stitches) * base_cm
    worked = sum(1 for s in all_stitches if s not in NOT_WORKED)
    return {
        "rounds": table,
        "final_stitches": rounds[-1].produced,
        "shape": shape_of(rounds),
        "increase_pct": increase_pct(rounds),
        "yarn_m": round(total_cm / 100, 2),
        "base_cm": base_cm,
        "minutes": round(worked / spm, 1),
        "spm": spm,
    }


def checklist(rounds, title):
    """Markdown working checklist, one tick box per round."""
    lines = [f"# {title} checklist", ""]
    for r in rounds:
        lines.append(f"- [ ] R{r.number} ({r.produced} st): {r.body}")
    return "\n".join(lines) + "\n"


def _positive_float(value):
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {value}")
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def _format_issue(path, issue):
    return f"{path}:{issue.line}:{issue.col}: {issue.severity}: {issue.message}"


def _summary_text(path, data):
    lines = [f"{'Round':<7}{'Consumed':>9}{'Produced':>9}{'Net':>7}"]
    for row in data["rounds"]:
        net = "start" if row["net"] is None else f"{row['net']:+d}"
        lines.append(f"R{row['number']:<6}{row['consumed']:>9}{row['produced']:>9}{net:>7}")
    shape = data["shape"]
    if data["increase_pct"] is not None:
        shape += f", mean increase {data['increase_pct']}% per round"
    lines += [
        "",
        f"Shape: {shape}",
        f"Final stitches: {data['final_stitches']}",
        f"Yarn: {data['yarn_m']} m (estimate, {data['base_cm']} cm per sc)",
        f"Work time: {data['minutes']} min at {data['spm']:g} stitches per minute",
    ]
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="hookcount",
        description="Offline crochet round-pattern checker: stitch counts, shape, yarn, time and checklists.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="verify stitch counts and lint the pattern")
    check.add_argument("file", help="plain-text pattern file")
    check.add_argument("--strict", action="store_true", help="treat warnings as failures")
    check.add_argument("--json", action="store_true", help="print machine-readable output")

    summary = sub.add_parser("summary", help="round table, shape, yarn and time estimates")
    summary.add_argument("file", help="plain-text pattern file")
    summary.add_argument("--base-cm", type=_positive_float, default=3.0,
                         help="yarn used by one sc, in cm (default: 3.0)")
    summary.add_argument("--spm", type=_positive_float, default=30.0,
                         help="worked stitches per minute (default: 30)")
    summary.add_argument("--json", action="store_true", help="print machine-readable output")

    lst = sub.add_parser("checklist", help="print a Markdown working checklist")
    lst.add_argument("file", help="plain-text pattern file")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        with open(args.file, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        print(f"hookcount: cannot read {args.file}: {exc.strerror}", file=sys.stderr)
        return 2
    except UnicodeDecodeError:
        print(f"hookcount: {args.file} is not UTF-8 text", file=sys.stderr)
        return 2

    rounds, issues = parse_pattern(text)
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]

    if args.command == "check":
        failed = bool(errors) or (args.strict and bool(warnings))
        if args.json:
            print(json.dumps({
                "file": args.file,
                "ok": not failed,
                "rounds": [
                    {"number": r.number, "consumed": r.consumed,
                     "produced": r.produced, "bracket": r.bracket}
                    for r in rounds
                ],
                "issues": [vars(i) for i in issues],
            }, indent=2))
        else:
            for issue in issues:
                print(_format_issue(args.file, issue))
            if failed:
                print(f"FAILED: {len(errors)} error(s), {len(warnings)} warning(s)")
            elif rounds:
                print(f"ok: {len(rounds)} rounds, {rounds[-1].produced} stitches in the last round"
                      + (f", {len(warnings)} warning(s)" if warnings else ""))
        return 1 if failed else 0

    if errors:
        for issue in issues:
            print(_format_issue(args.file, issue), file=sys.stderr)
        print("hookcount: fix the errors before summarising or listing", file=sys.stderr)
        return 1

    if args.command == "summary":
        data = summarise(rounds, args.base_cm, args.spm)
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print(_summary_text(args.file, data))
        return 0

    title = os.path.splitext(os.path.basename(args.file))[0]
    sys.stdout.write(checklist(rounds, title))
    return 0


if __name__ == "__main__":
    sys.exit(main())
