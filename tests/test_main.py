"""upbit_main.py: 인자 파싱과 로깅 준비. 임포트만으로는 부작용이 없어야 한다."""

import pytest

from upbit_main import parse_args, setup_logging


def test_defaults_are_monitor_and_conservative():
    args = parse_args([])
    assert (args.mode, args.strategy) == ("monitor", "conservative")
    assert (args.capital, args.days) == (1_000_000, 1095)


def test_legacy_mode_name_maps_to_monitor():
    # README의 기존 명령 (--mode monitor-default)이 계속 동작해야 한다.
    assert parse_args(["--mode", "monitor-default"]).mode == "monitor"


def test_backtest_options():
    args = parse_args(
        ["--mode", "backtest", "--strategy", "aggressive", "--capital", "500000", "--days", "365"]
    )
    assert args.mode == "backtest"
    assert args.strategy == "aggressive"
    assert (args.capital, args.days) == (500_000.0, 365)


@pytest.mark.parametrize("argv", [["--strategy", "bogus"], ["--mode", "both"]])
def test_unknown_choices_are_rejected(argv):
    with pytest.raises(SystemExit):
        parse_args(argv)


def test_setup_logging_creates_missing_directory(tmp_path):
    log_dir = tmp_path / "upbit_output_files" / "logs"
    log_file = setup_logging(log_dir)
    assert log_dir.is_dir()
    assert log_file.parent == log_dir
    assert log_file.name.startswith("upbit_monitor_") and log_file.suffix == ".log"
