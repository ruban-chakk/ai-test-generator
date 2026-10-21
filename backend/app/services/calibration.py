from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable


ALLOWED_LABELS = {"duplicate", "update", "unrelated"}


@dataclass(frozen=True)
class CalibrationSample:
    similarity: float
    expected_action: str


@dataclass(frozen=True)
class CalibrationResult:
    duplicate_threshold: float
    update_threshold: float
    accuracy: float
    macro_f1: float
    confusion: dict[str, dict[str, int]]
    label_distribution: dict[str, int]


def calibrate_thresholds(samples: Iterable[CalibrationSample]) -> CalibrationResult:
    items = list(samples)
    if len(items) < 10:
        raise ValueError("At least 10 labeled samples are required")
    if any(item.expected_action not in ALLOWED_LABELS for item in items):
        raise ValueError("Expected action must be duplicate, update, or unrelated")
    if any(item.similarity < 0 or item.similarity > 1 for item in items):
        raise ValueError("Similarity scores must be between 0 and 1")
    distribution = Counter(item.expected_action for item in items)
    if any(distribution[label] == 0 for label in ALLOWED_LABELS):
        raise ValueError("The calibration set must include every expected action")

    candidates = sorted({0.0, 1.0, *[round(item.similarity, 4) for item in items]})
    best: tuple[float, float, float, float, dict[str, dict[str, int]]] | None = None
    for update_threshold in candidates:
        for duplicate_threshold in candidates:
            if update_threshold >= duplicate_threshold:
                continue
            confusion = _confusion(items, update_threshold, duplicate_threshold)
            accuracy = sum(confusion[label][label] for label in ALLOWED_LABELS) / len(items)
            macro_f1 = sum(_f1(confusion, label) for label in ALLOWED_LABELS) / len(ALLOWED_LABELS)
            candidate = (macro_f1, accuracy, duplicate_threshold, update_threshold, confusion)
            if best is None or candidate[:2] > best[:2] or (
                candidate[:2] == best[:2]
                and abs(duplicate_threshold - 0.8) + abs(update_threshold - 0.45)
                < abs(best[2] - 0.8) + abs(best[3] - 0.45)
            ):
                best = candidate
    if best is None:
        raise ValueError("The calibration set cannot produce ordered thresholds")
    macro_f1, accuracy, duplicate_threshold, update_threshold, confusion = best
    return CalibrationResult(
        duplicate_threshold=duplicate_threshold,
        update_threshold=update_threshold,
        accuracy=round(accuracy, 4),
        macro_f1=round(macro_f1, 4),
        confusion=confusion,
        label_distribution=dict(distribution),
    )


def _predict(similarity: float, update_threshold: float, duplicate_threshold: float) -> str:
    if similarity >= duplicate_threshold:
        return "duplicate"
    if similarity >= update_threshold:
        return "update"
    return "unrelated"


def _confusion(
    samples: list[CalibrationSample],
    update_threshold: float,
    duplicate_threshold: float,
) -> dict[str, dict[str, int]]:
    matrix = {expected: {predicted: 0 for predicted in sorted(ALLOWED_LABELS)} for expected in sorted(ALLOWED_LABELS)}
    for sample in samples:
        matrix[sample.expected_action][_predict(sample.similarity, update_threshold, duplicate_threshold)] += 1
    return matrix


def _f1(confusion: dict[str, dict[str, int]], label: str) -> float:
    true_positive = confusion[label][label]
    false_positive = sum(confusion[expected][label] for expected in ALLOWED_LABELS if expected != label)
    false_negative = sum(confusion[label][predicted] for predicted in ALLOWED_LABELS if predicted != label)
    denominator = (2 * true_positive) + false_positive + false_negative
    return (2 * true_positive / denominator) if denominator else 0.0
