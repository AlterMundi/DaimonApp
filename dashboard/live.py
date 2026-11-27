"""Local write notifications for authenticated, read-only conversation streams."""
import asyncio
import ctypes
import os
import struct


async def changes(paths, heartbeat=15, subscriptions=None):
    """Watch owned sources, including SQLite WAL and atomic observer replacement.

    Notifications only invalidate a view. Canonical cursors remain in the existing
    presentation API; reconnect always requests catch-up and never submits work.
    """
    libc = ctypes.CDLL(None, use_errno=True)
    fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
    if fd < 0:
        raise OSError(ctypes.get_errno(), 'Conversation notifications unavailable')
    loop = asyncio.get_running_loop()
    wake = asyncio.Event()
    selected = {}
    subscriptions = subscriptions or {}
    closers = []
    pending = {'conversation', *subscriptions}
    def invalidate(channel):
        pending.add(channel)
        wake.set()
    def take_changes():
        changed = set(pending)
        pending.clear()
        wake.clear()
        return changed
    try:
        directories = {}
        for path in paths:
            directories.setdefault(path.parent, set()).update((path.name, path.name+'-wal', path.name+'-journal'))
        for directory, names in directories.items():
            wd = libc.inotify_add_watch(fd, os.fsencode(directory), 0x2 | 0x8 | 0x80 | 0x100 | 0x200 | 0x400 | 0x800)
            if wd < 0:
                raise OSError(ctypes.get_errno(), 'Conversation source watch unavailable')
            selected[wd] = names
        def readable():
            try:
                data = os.read(fd, 65536)
            except BlockingIOError:
                return
            offset = 0
            while offset + 16 <= len(data):
                wd, mask, _, size = struct.unpack_from('iIII', data, offset)
                name = os.fsdecode(data[offset+16:offset+16+size].split(b'\0', 1)[0])
                offset += 16 + size
                if mask & (0x4000 | 0x400 | 0x800) or name in selected.get(wd, ()):
                    invalidate('conversation')
        loop.add_reader(fd, readable)
        for channel, subscribe in subscriptions.items():
            closers.append(subscribe(lambda channel=channel: loop.call_soon_threadsafe(invalidate, channel)))
        # Watches are installed before initial catch-up, closing the startup gap.
        yield take_changes()
        while True:
            try:
                # Python3.11 wait_for may return a concurrent wakeup instead of
                # propagating external cancellation. Keep the heartbeat in this
                # task so closing a voice/SSE owner always releases its watch.
                async with asyncio.timeout(heartbeat):
                    await wake.wait()
                # Collapse a transaction/atomic replacement into one invalidation.
                await asyncio.sleep(.1)
                yield take_changes()
            except asyncio.TimeoutError:
                yield set()
    finally:
        for unsubscribe in reversed(closers):
            unsubscribe()
        loop.remove_reader(fd)
        os.close(fd)
