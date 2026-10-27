import random
import unittest
from quizbot.domain import (
    UserError,
    validate_question,
    validate_timing,
    shuffled,
    score,
    Rank,
    ranked,
    next_status,
    can_manage_private,
)
from quizbot.demo import DEMO


class DomainTests(unittest.TestCase):
    def test_valid_question(self):
        validate_question("Savol?", ["A", "B"], 1, "Izoh")

    def test_empty_question(self):
        with self.assertRaises(UserError):
            validate_question("", ["A", "B"], 0)

    def test_long_question(self):
        with self.assertRaises(UserError):
            validate_question("x" * 301, ["A", "B"], 0)

    def test_bad_options(self):
        for options in [["A"], ["A"] * 5, ["A", "A"], ["", "B"], ["x" * 101, "B"]]:
            with self.subTest(options=options), self.assertRaises(UserError):
                validate_question("Savol?", options, 0)

    def test_invalid_correct(self):
        for value in [-1, 2]:
            with self.assertRaises(UserError):
                validate_question("Savol?", ["A", "B"], value)

    def test_explanation_limit(self):
        for text in ["x" * 201, "a\nb\nc\nd"]:
            with self.assertRaises(UserError):
                validate_question("Savol?", ["A", "B"], 0, text)

    def test_boundary_lengths(self):
        validate_question("x" * 300, ["x" * 100, "y" * 100], 1, "x" * 200)

    def test_shuffled_correctness(self):
        for seed in range(100):
            result, correct, order = shuffled(["A", "B", "C", "D"], 2, random.Random(seed))
            self.assertEqual(result[correct], "C")
            self.assertEqual(sorted(order), [0, 1, 2, 3])
            self.assertEqual(result, [["A", "B", "C", "D"][i] for i in order])

    def test_timing_valid(self):
        for interval in [60, 86400]:
            for duration in [5, 30, 2628000]:
                validate_timing(interval, duration)

    def test_timing_invalid(self):
        for interval, duration in [
            (0, 30),
            (59, 30),
            (61, 30),
            (86460, 30),
            (60, 4),
            (60, 2628001),
        ]:
            with self.assertRaises(UserError):
                validate_timing(interval, duration)

    def test_scoring_and_withdrawal(self):
        self.assertEqual(score(1, 1), 1)
        self.assertEqual(score(0, 1), 0)
        self.assertEqual(score(None, 1), 0)

    def test_rank_order(self):
        rows = [
            Rank(4, "D", 2, 0, 400),
            Rank(3, "C", 2, 1, 300),
            Rank(2, "B", 2, 0, 300),
            Rank(1, "A", 3, 1, 5000),
        ]
        self.assertEqual([r.user_id for r in ranked(rows)], [1, 2, 3, 4])
        self.assertEqual(rows[1].answered, 3)
        self.assertAlmostEqual(rows[1].accuracy, 200 / 3)

    def test_empty_accuracy(self):
        self.assertEqual(Rank(1, "A", 0, 0, 0).accuracy, 0)

    def test_pause_resume_stop(self):
        self.assertEqual(next_status("active", "pause"), "paused")
        self.assertEqual(next_status("paused", "resume"), "active")
        self.assertEqual(next_status("active", "stop"), "stopping")
        self.assertEqual(next_status("paused", "stop"), "stopping")

    def test_invalid_transition(self):
        for status, action in [
            ("finished", "resume"),
            ("active", "resume"),
            ("paused", "pause"),
            ("blocked", "stop"),
        ]:
            with self.assertRaises(UserError):
                next_status(status, action)

    def test_private_owner(self):
        self.assertTrue(can_manage_private(123, 123))
        self.assertFalse(can_manage_private(123, 456))

    def test_demo_valid_and_complete(self):
        self.assertEqual(set(DEMO), {"JavaScript", "Python", "Umumiy bilim"})
        for rows in DEMO.values():
            self.assertGreaterEqual(len(rows), 5)
            for row in rows:
                validate_question(*row)


if __name__ == "__main__":
    unittest.main()
