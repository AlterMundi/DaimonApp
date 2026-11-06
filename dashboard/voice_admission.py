"""Cooperating web maintenance and voice share one persistent OS lock.

No account/goal/provider control, retry, polling or independent native CLI fence.
The file is constant-size and must never be replaced/unlinked during operation.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
import stat
import threading
from typing import NamedTuple

from .private_state import private_directory

HEADER = 'X-DaimonApp-Voice-Admission'
SCOPE_KEY = 'daimon.voice_admission'


def _open(root, uid, create=False):
    folder = Path(root) / 'voice-admission'
    if create:
        private_directory(folder)
    info = folder.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077:
        raise ValueError('Voice admission directory needs owner-only access')
    fd = os.open(folder / '.lock', os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC |
                 (os.O_CREAT if create else 0), 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077
                or info.st_size != 0 or info.st_nlink != 1):
            raise ValueError('Voice admission requires its existing private empty lock')
        identity = hashlib.sha256(f'{info.st_dev}:{info.st_ino}:{info.st_uid}'.encode()).hexdigest()
        return fd, 'flock-v1:' + identity
    except BaseException:
        os.close(fd)
        raise


class Claim:
    def __init__(self, fd, header):
        self.fd, self.header = fd, header
        self._references = 1
        self._guard = threading.RLock()

    def retain(self):
        with self._guard:
            if not self._references:
                raise ValueError('Voice admission already ended')
            self._references += 1

    def release(self):
        with self._guard:
            if self._references:
                self._references -= 1
                if not self._references:
                    os.close(self.fd)

    def hold_until(self, task):
        self.retain()
        loop = task.get_loop()
        # Let the resource owner's already registered late-close callbacks run
        # before dropping this reference. No extra cleanup or work is started.
        task.add_done_callback(lambda _: loop.call_soon(self.release))


class VoiceAdmission:
    def __init__(self, root):
        self.root = Path(root)
        fd, self.header = _open(self.root, os.getuid(), create=True)
        os.close(fd)

    def claim(self):
        fd, header = _open(self.root, os.getuid())
        try:
            if header != self.header:
                raise ValueError('Voice admission lock changed; operator must inspect')
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            return Claim(fd, header)
        except BaseException:
            os.close(fd)
            raise


class Maintenance(NamedTuple):
    fd: int
    header: str


@contextmanager
def maintenance_guard(root, *, owner_uid=None):
    """Hold through the existing finite operator, health and outcome checks.

    After acquiring, match guard.header against the actual local health HEADER.
    Older readers without that header support observed-idle bootstrap only.
    """
    fd, header = _open(root, os.getuid() if owner_uid is None else owner_uid)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield Maintenance(fd,header)
    finally:
        os.close(fd)


class VoiceAdmissionError(ValueError):
    pass


def admission_failure(error):
    return str(error) if isinstance(error,VoiceAdmissionError) else None


class _Ticket:
    """Transport lifetime; acquire only after the existing actor/CSRF check."""
    def __init__(self, admission):
        self.admission=admission;self.claim=None;self.finished=False
        self._guard=threading.RLock()

    def activate(self):
        with self._guard:
            if self.finished:raise VoiceAdmissionError('Voice activation already ended.')
            if self.claim is not None:return
            try:self.claim=self.admission.claim()
            except BlockingIOError:
                raise VoiceAdmissionError('Voice is temporarily unavailable during a server update. Try again when it is ready; no new recording or work was submitted.') from None
            except (OSError,ValueError):
                raise VoiceAdmissionError('Voice setup could not be verified. Your recordings and work are kept; the server needs review.') from None

    def reference(self):
        with self._guard:
            if self.finished or self.claim is None:raise ValueError('Voice admission already ended')
            self.claim.retain();return self.claim

    def hold_until(self, task):
        with self._guard:
            if self.claim is not None:self.claim.hold_until(task)

    def release(self):
        with self._guard:
            if not self.finished:
                self.finished=True
                if self.claim is not None:self.claim.release()


def admit_voice(scope):
    ticket=scope.get(SCOPE_KEY)
    if ticket is not None:ticket.activate()


def hold_voice_task(scope, task):
    claim=scope.get(SCOPE_KEY)
    if claim is not None:claim.hold_until(task)


@contextmanager
def retained_voice(scope):
    claim=scope.get(SCOPE_KEY)
    if isinstance(claim,_Ticket):claim=claim.reference()
    elif claim is not None:claim.retain()
    try:
        yield
    finally:
        if claim is not None:claim.release()


class VoiceAdmissionMiddleware:
    def __init__(self, app, admission):
        self.app,self.admission=app,admission

    async def __call__(self, scope, receive, send):
        if scope['type']!='websocket' or not scope['path'].startswith('/api/interaction/voice/'):
            return await self.app(scope,receive,send)
        ticket=_Ticket(self.admission);scope[SCOPE_KEY]=ticket
        try:await self.app(scope,receive,send)
        finally:ticket.release()
