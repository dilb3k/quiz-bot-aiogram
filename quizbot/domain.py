from dataclasses import dataclass
import random


class UserError(Exception):
    pass


def validate_question(text: str, options: list[str], correct: int, explanation: str = "") -> None:
    if not 1 <= len(text.strip()) <= 300:
        raise UserError("Savol 1–300 belgidan iborat bo‘lsin.")
    if not 2 <= len(options) <= 4 or any(not 1 <= len(x.strip()) <= 100 for x in options):
        raise UserError("2–4 ta variant kiriting. Har biri 1–100 belgi bo‘lsin.")
    if len(set(options)) != len(options):
        raise UserError("Variantlar bir-biridan farq qilsin.")
    if correct not in range(len(options)):
        raise UserError("To‘g‘ri variant raqami noto‘g‘ri.")
    if len(explanation) > 200 or explanation.count("\n") > 2:
        raise UserError("Tushuntirish ko‘pi bilan 200 belgi va 2 ta yangi qator bo‘lsin.")


def validate_timing(interval: int, duration: int) -> None:
    if not 60 <= interval <= 86400 or interval % 60:
        raise UserError("Interval 1–1440 butun minut bo‘lsin.")
    if not 5 <= duration <= 2628000:
        raise UserError("Javob muddati 5–2628000 soniya bo‘lsin.")


def shuffled(
    options: list[str], correct: int, rng: random.Random | None = None
) -> tuple[list[str], int, list[int]]:
    order = list(range(len(options)))
    (rng or random.SystemRandom()).shuffle(order)
    return [options[i] for i in order], order.index(correct), order


def score(option: int | None, correct: int) -> int:
    return int(option is not None and option == correct)


def can_manage_private(owner: int, actor: int) -> bool:
    return owner == actor


def next_status(status: str, action: str) -> str:
    transitions = {
        ("active", "pause"): "paused",
        ("paused", "resume"): "active",
        ("active", "stop"): "stopping",
        ("paused", "stop"): "stopping",
    }
    if (status, action) not in transitions:
        raise UserError("Bu amal sessiyaning joriy holatida bajarilmaydi.")
    return transitions[status, action]


@dataclass
class Rank:
    user_id: int
    name: str
    correct: int
    wrong: int
    elapsed: int

    @property
    def answered(self) -> int:
        return self.correct + self.wrong

    @property
    def accuracy(self) -> float:
        return 100 * self.correct / self.answered if self.answered else 0


def ranked(rows: list[Rank]) -> list[Rank]:
    return sorted(rows, key=lambda r: (-r.correct, r.elapsed, r.user_id))
