import pytest

from app.services.calibration import CalibrationSample, calibrate_thresholds


def _labeled_samples() -> list[CalibrationSample]:
    return [
        CalibrationSample(0.96, "duplicate"),
        CalibrationSample(0.91, "duplicate"),
        CalibrationSample(0.86, "duplicate"),
        CalibrationSample(0.74, "update"),
        CalibrationSample(0.68, "update"),
        CalibrationSample(0.57, "update"),
        CalibrationSample(0.41, "unrelated"),
        CalibrationSample(0.30, "unrelated"),
        CalibrationSample(0.20, "unrelated"),
        CalibrationSample(0.10, "unrelated"),
    ]


def test_calibration_finds_ordered_thresholds_with_reproducible_metrics() -> None:
    result = calibrate_thresholds(_labeled_samples())

    assert result.update_threshold < result.duplicate_threshold
    assert result.accuracy == 1.0
    assert result.macro_f1 == 1.0
    assert result.label_distribution == {"duplicate": 3, "update": 3, "unrelated": 4}


def test_calibration_rejects_unrepresentative_data() -> None:
    with pytest.raises(ValueError, match="every expected action"):
        calibrate_thresholds([CalibrationSample(index / 10, "update") for index in range(10)])
