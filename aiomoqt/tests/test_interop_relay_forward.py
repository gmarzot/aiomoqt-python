"""The relay's per-track forward loop must survive an upstream subgroup
END and keep forwarding later groups (a dead loop drops every group
after the first, invisibly to a subscriber that only checks group 0)."""
import asyncio

import pytest

from aiomoqt.context import profile_for
from aiomoqt.tools.moq_interop_relay import _RelayedTrack


class _Downstream:
    def __init__(self):
        self._profile = profile_for(18)
        self._next = 3
        self.writes = []            # (stream_id, nbytes, fin)

    async def open_uni_stream(self):
        sid = self._next
        self._next += 4
        return sid

    def stream_write(self, sid, data, end_stream=False):
        self.writes.append((sid, len(data), end_stream))

    async def stream_write_drain(self, sid, data):
        self.writes.append((sid, len(data), False))


@pytest.mark.asyncio
async def test_forward_loop_survives_subgroup_end():
    track = _RelayedTrack(("ns", "t"))
    down = _Downstream()
    track.downstream.append((down, 7, 1))
    loop_task = asyncio.create_task(track._forward_loop())

    track.on_object(_Obj(group_id=0, object_id=0), 0, 0, 0, 0)
    track.on_stream_end(0, 0)
    track.on_object(_Obj(group_id=1, object_id=0), 0, 0, 1, 0)
    for _ in range(20):
        await asyncio.sleep(0)
    loop_task.cancel()

    assert not loop_task.done() or loop_task.cancelled()
    streams = {sid for sid, _n, _fin in down.writes}
    assert len(streams) == 2                       # group 0 and group 1
    assert any(fin for _sid, _n, fin in down.writes)  # group 0 was FINed


class _Obj:
    def __init__(self, group_id, object_id):
        self.group_id = group_id
        self.object_id = object_id
        self.payload = b"x" * 8
        self.extensions = None
        self.publisher_priority = 128
        self.status = None
        self.stream_flags = None
