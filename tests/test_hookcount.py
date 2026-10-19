import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import hookcount  # noqa: E402

EXAMPLE = ROOT / "examples" / "beanie.txt"
BROKEN = ROOT / "examples" / "beanie_broken.txt"


def _errors(issues):
    return [i for i in issues if i.severity == "error"]


def _warnings(issues):
    return [i for i in issues if i.severity == "warning"]


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = hookcount.main(argv)
    return code, out.getvalue(), err.getvalue()


class ParseTests(unittest.TestCase):
    def test_example_pattern_is_clean(self):
        rounds, issues = hookcount.parse_pattern(EXAMPLE.read_text(encoding="utf-8"))
        self.assertEqual(issues, [])
        self.assertEqual(len(rounds), 9)
        self.assertEqual(rounds[-1].produced, 6)

    def test_group_repeats_are_expanded(self):
        rounds, issues = hookcount.parse_pattern("R1: (sc, inc) x3 [9]\n")
        self.assertEqual(issues, [])
        self.assertEqual(len(rounds[0].stitches), 6)
        self.assertEqual(rounds[0].produced, 9)
        self.assertEqual(rounds[0].consumed, 6)

    def test_count_suffix_applies_to_one_token(self):
        rounds, _ = hookcount.parse_pattern("R1: MR, sc6 [6]\n")
        self.assertEqual(rounds[0].stitches.count("sc"), 6)
        self.assertEqual(rounds[0].produced, 6)

    def test_bracket_mismatch_points_at_bracket_column(self):
        _, issues = hookcount.parse_pattern("R1: sc6 [5]\n")
        errors = _errors(issues)
        self.assertEqual(len(errors), 1)
        self.assertIn("makes 6 stitches", errors[0].message)
        self.assertEqual((errors[0].line, errors[0].col), (1, 9))

    def test_unknown_stitch_reports_line_and_column(self):
        _, issues = hookcount.parse_pattern("R1: MR, sc6 [6]\nR2: sc6, qq [6]\n")
        errors = _errors(issues)
        self.assertEqual(len(errors), 1)
        self.assertIn("unknown stitch 'qq'", errors[0].message)
        self.assertEqual(errors[0].line, 2)
        self.assertEqual(errors[0].col, 10)

    def test_consumption_must_match_previous_round(self):
        _, issues = hookcount.parse_pattern("R1: MR, sc6 [6]\nR2: sc5 [5]\n")
        messages = [i.message for i in _errors(issues)]
        self.assertTrue(any("works into 5 stitches but R1 made 6" in m for m in messages))

    def test_magic_ring_only_allowed_in_round_one(self):
        _, issues = hookcount.parse_pattern("R1: MR, sc6 [6]\nR2: inc6 [12]\nR3: MR, sc12 [12]\n")
        self.assertTrue(any("magic ring is only valid in R1" in i.message for i in _errors(issues)))

    def test_round_numbers_must_be_sequential(self):
        _, issues = hookcount.parse_pattern("R1: MR, sc6 [6]\nR3: inc6 [12]\n")
        self.assertTrue(any("expected R2, found R3" in i.message for i in _errors(issues)))

    def test_missing_bracket_is_only_a_warning(self):
        _, issues = hookcount.parse_pattern("R1: MR, sc6\n")
        self.assertEqual(_errors(issues), [])
        self.assertEqual(len(_warnings(issues)), 1)

    def test_doubling_round_warns_about_missed_repeat(self):
        _, issues = hookcount.parse_pattern("R1: MR, sc6 [6]\nR2: inc6, sc1 [13]\n")
        self.assertTrue(any("more than doubles" in i.message for i in _warnings(issues)))

    def test_comments_and_blank_lines_are_ignored(self):
        text = "# header\n\nR1: MR, sc6 [6]  # trailing note\n   \n"
        rounds, issues = hookcount.parse_pattern(text)
        self.assertEqual(issues, [])
        self.assertEqual(len(rounds), 1)

    def test_zero_repeat_is_an_error(self):
        _, issues = hookcount.parse_pattern("R1: MR, (sc) x0 [0]\n")
        self.assertTrue(any("group repeat must be at least 1" in i.message for i in _errors(issues)))

    def test_empty_file_has_no_rounds(self):
        rounds, issues = hookcount.parse_pattern("# nothing here\n")
        self.assertEqual(rounds, [])
        self.assertEqual(issues[0].message, "no rounds found")


class AnalysisTests(unittest.TestCase):
    def test_shape_flat_increasing_decreasing_mixed(self):
        flat, _ = hookcount.parse_pattern("R1: MR, sc6 [6]\nR2: sc6 [6]\n")
        up, _ = hookcount.parse_pattern("R1: MR, sc6 [6]\nR2: inc6 [12]\n")
        down, _ = hookcount.parse_pattern("R1: MR, sc6 [6]\nR2: dec3 [3]\n")
        mixed, _ = hookcount.parse_pattern("R1: MR, sc6 [6]\nR2: inc6 [12]\nR3: dec6 [6]\n")
        self.assertEqual(hookcount.shape_of(flat), "flat")
        self.assertEqual(hookcount.shape_of(up), "increasing")
        self.assertEqual(hookcount.shape_of(down), "decreasing")
        self.assertEqual(hookcount.shape_of(mixed), "mixed")

    def test_increase_percentage_uses_rounds_that_grow(self):
        rounds, _ = hookcount.parse_pattern("R1: MR, sc6 [6]\nR2: inc6 [12]\nR3: sc12 [12]\n")
        self.assertEqual(hookcount.increase_pct(rounds), 100.0)

    def test_yarn_and_time_estimates(self):
        rounds, _ = hookcount.parse_pattern("R1: MR, sc6 [6]\n")
        data = hookcount.summarise(rounds, base_cm=3.0, spm=30.0)
        self.assertEqual(data["yarn_m"], 0.18)
        self.assertEqual(data["minutes"], 0.2)
        self.assertEqual(data["final_stitches"], 6)

    def test_summary_totals_for_example(self):
        rounds, _ = hookcount.parse_pattern(EXAMPLE.read_text(encoding="utf-8"))
        data = hookcount.summarise(rounds)
        self.assertEqual(data["shape"], "mixed")
        self.assertEqual(len(data["rounds"]), 9)
        self.assertIsNone(data["rounds"][0]["net"])
        self.assertEqual(data["rounds"][1]["net"], 6)

    def test_checklist_has_one_box_per_round(self):
        rounds, _ = hookcount.parse_pattern("R1: MR, sc6 [6]\nR2: inc6 [12]\n")
        text = hookcount.checklist(rounds, "hat")
        self.assertIn("# hat checklist", text)
        self.assertIn("- [ ] R2 (12 st): inc6", text)
        self.assertEqual(text.count("- [ ]"), 2)


class CliTests(unittest.TestCase):
    def test_check_passes_on_example(self):
        code, out, _ = _run(["check", str(EXAMPLE)])
        self.assertEqual(code, 0)
        self.assertIn("ok: 9 rounds", out)

    def test_check_fails_on_broken_pattern(self):
        code, out, _ = _run(["check", str(BROKEN)])
        self.assertEqual(code, 1)
        self.assertIn("FAILED:", out)
        self.assertIn("the bracket says [19]", out)

    def test_strict_mode_fails_on_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nobracket.txt")
            Path(path).write_text("R1: MR, sc6\n", encoding="utf-8")
            self.assertEqual(_run(["check", path])[0], 0)
            self.assertEqual(_run(["check", path, "--strict"])[0], 1)

    def test_check_json_output_is_parseable(self):
        code, out, _ = _run(["check", str(BROKEN), "--json"])
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertFalse(data["ok"])
        self.assertTrue(all({"line", "col", "severity", "message"} <= set(i) for i in data["issues"]))

    def test_summary_json_matches_library(self):
        code, out, _ = _run(["summary", str(EXAMPLE), "--json", "--spm", "40"])
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(data["spm"], 40.0)
        self.assertEqual(data["final_stitches"], 6)

    def test_summary_refuses_broken_pattern(self):
        code, out, err = _run(["summary", str(BROKEN)])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("fix the errors", err)

    def test_checklist_command_prints_markdown(self):
        code, out, _ = _run(["checklist", str(EXAMPLE)])
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("# beanie checklist"))

    def test_missing_file_exits_with_usage_code(self):
        code, _, err = _run(["check", str(ROOT / "does-not-exist.txt")])
        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)

    def test_non_positive_spm_is_rejected(self):
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                hookcount.build_parser().parse_args(["summary", "x.txt", "--spm", "0"])


if __name__ == "__main__":
    unittest.main()
