import logging
import sys
from pathlib import Path
from types import SimpleNamespace


# Allow importing scripts from the edge/scr directory.
sys.path.append(str(Path(__file__).resolve().parents[1] / "edge" / "scr"))


import acquire  # type: ignore  # noqa: E402


class DummyBoard:
    def __init__(self, name: str):
        self.name = name
        self.stop_calls = 0
        self.cleanup_calls = 0
        self.closed = False

    def a_in_scan_stop(self):
        self.stop_calls += 1

    def a_in_scan_cleanup(self):
        self.cleanup_calls += 1

    def close(self):
        self.closed = True


class DummySender:
    def __init__(self):
        self.lines = []
        self.closed = False

    def enqueue(self, line: str):  # pragma: no cover - simple collector
        self.lines.append(line)

    def close(self):
        self.closed = True


def test_acquire_reconnects_after_read_errors(monkeypatch, caplog):
    boards = []
    start_calls = []
    sleep_calls = []
    senders = []

    def fake_open_mcc128():
        board = DummyBoard(f"board{len(boards) + 1}")
        boards.append(board)
        return board

    def fake_start_scan(board, channels, fs, v_range, block_size):
        start_calls.append((board.name, block_size))
        return 0x1, block_size

    actions = iter(["runtime", "runtime", "runtime", "success", "runtime", "keyboard"])

    def fake_read_block(board, ch_mask, block, channels, sample_rate_hz=None):
        action = next(actions)
        if action == "runtime":
            raise RuntimeError("boom")
        if action == "success":
            return {channels[0]: [1.23]}
        raise KeyboardInterrupt

    def fake_sleep(seconds):
        sleep_calls.append(seconds)

    config = {
        "station_id": "pi-test",
        "sample_rate_hz": 10,
        "scan_block_size": 2,
        "scan_retry_backoff_s": 0,
        "scan_max_retries": 2,
        "channels": [
            {
                "ch": 0,
                "sensor": "sensor-0",
                "unit": "u",
                "calib": {"gain": 1.0, "offset": 0.0},
            }
        ],
    }

    monkeypatch.setattr(acquire, "open_mcc128", fake_open_mcc128)
    monkeypatch.setattr(acquire, "start_scan", fake_start_scan)
    monkeypatch.setattr(acquire, "read_block", fake_read_block)
    monkeypatch.setattr(acquire.yaml, "safe_load", lambda _: config)
    monkeypatch.setattr(acquire, "InfluxSender", lambda: senders.append(DummySender()) or senders[-1])
    monkeypatch.setattr(acquire, "time_ns", lambda: 1_500_000_000)
    monkeypatch.setattr(acquire.time, "sleep", fake_sleep)
    monkeypatch.setattr(acquire, "AnalogInputRange", SimpleNamespace(BIP_10V=object()))
    monkeypatch.chdir(Path(__file__).resolve().parents[1] / "edge")

    caplog.set_level(logging.WARNING, logger=acquire.logger.name)

    acquire.main()

    assert len(boards) == 2
    assert boards[0].stop_calls == boards[0].cleanup_calls == 3
    assert boards[0].closed is True
    assert boards[1].stop_calls == boards[1].cleanup_calls == 2

    assert sleep_calls == [0, 0, 0, 0]
    assert start_calls == [
        ("board1", 2),
        ("board1", 2),
        ("board1", 2),
        ("board2", 2),
        ("board2", 2),
    ]

    assert senders and senders[0].closed is True
    assert len(senders[0].lines) == 1

    warning_messages = [rec.getMessage() for rec in caplog.records if rec.levelno == logging.WARNING]
    assert warning_messages[0].startswith("Fallo en read_block (intento 1/2)")
    assert warning_messages[1].startswith("Fallo en read_block (intento 2/2)")
    assert warning_messages[2].startswith("Fallo en read_block (intento 3/2)")
    assert warning_messages[3].startswith("Fallo en read_block (intento 1/2)")

    error_messages = [rec.getMessage() for rec in caplog.records if rec.levelno == logging.ERROR]
    assert any("reabriendo MCC128" in msg for msg in error_messages)
