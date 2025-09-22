from edge.scr.acquire import _consume_block_timestamps  # type: ignore  # noqa: E402


def test_consecutive_blocks_preserve_ts_step():
    """Two consecutive blocks must keep a constant ts_step."""

    ts_step = 1000
    start_ts = 1_000_000_000

    block1, next_ts = _consume_block_timestamps(start_ts, 4, ts_step)
    block2, next_ts = _consume_block_timestamps(next_ts, 3, ts_step)

    sequence = block1 + block2

    assert sequence[0] == start_ts
    assert sequence[-1] == start_ts + (len(sequence) - 1) * ts_step
    assert all(b - a == ts_step for a, b in zip(sequence, sequence[1:]))
