"""Serial Framed RF Device Communication Protocol
"""
import sys
import struct
import time
import threading
from warnings import warn

from . import cobs
from .util import adict
from .asyncq import AsyncQ


class Serf:
    SERF_CODE_PROTO_M   = 0b11100000
    SERF_CODE_PROTO_VAL = 0b10100000
    SERF_CODE_M         = 0b00011111
    SERF_DECODE_ERROR   = (0, None)

    cmds = None

    def __init__(self, write=None):
        self.io = adict()
        self.cmds = []
        self.serial = None
        self._sync = {}
        self._thread_input = None
        self._thread_write = None
        self._thread_proc = None
        self._write_q = AsyncQ(size=1024)
        self._proc_q = AsyncQ()
        self.write = write
        self.port = None

    def add(self, name, code=None, encode=None, decode=None, handle=None, response=None, multi=False):
        if encode is None:
            encode = lambda *args, **kwds: bytes()

        if decode is None:
            decode = lambda data: (code, data)

        if handle is None:
            handle = self.on_frame

        cmd = adict(
            name=name, code=code, response=response,
            encode=encode, decode=decode, multi=multi,
            handle=handle
        )

        self.cmds.append(cmd)

        if response is None:
            self.io[name] = lambda *args, **kwds: self._write(code, encode(*args, **kwds))

        else:
            if handle == self.on_frame:
                cmd.handle = handle = lambda *args: args

            _writer = None if code is None else \
                lambda *a, **k: self._write(code, encode(*a, **k))

            _sync = WaitSync(handle, _writer, multi)
            cmd.sync = _sync

            self.io[name] = _sync.write_wait

    @staticmethod
    def encode(code, data):
        if (code & Serf.SERF_CODE_M) != code:
            print("warning: code 0x{:02X} truncated to 0x{:02X}".format(code, code & Serf.SERF_CODE_M), file=sys.stderr)

        frame = struct.pack(f"<B{len(data)}s", Serf.SERF_CODE_PROTO_VAL | (code & Serf.SERF_CODE_M), data)
        frame = cobs.cobs_encode(frame)
        frame.append(0)
        return frame

    @staticmethod
    def decode(data):
        if len(data) <= 1:
            return Serf.SERF_DECODE_ERROR

        data = cobs.cobs_decode(data)

        if not len(data):
            print("serf: empty data", file=sys.stderr)
            return Serf.SERF_DECODE_ERROR

        code = data[0]

        if (code & Serf.SERF_CODE_PROTO_M) != Serf.SERF_CODE_PROTO_VAL:
            print("serf: bad proto val", file=sys.stderr)
            return Serf.SERF_DECODE_ERROR

        return code & Serf.SERF_CODE_M, data[1:]

    def open(self, tty, baud=115200):
        if self.serial is not None:
            self.close()
        else:
            import serial
            # self.serial = serial.Serial(timeout=0.01)
            self.serial = serial.Serial()

        self.port = self.serial.port = tty
        self.serial.baudrate = baud
        self.serial.open()

        self._thread_input = threading.Thread(target=self._input_thread)
        self._thread_input.setDaemon(True)
        self._thread_input.start()

        self._thread_write = threading.Thread(target=self._write_thread)
        self._thread_write.setDaemon(True)
        self._thread_write.start()

        self._thread_proc = threading.Thread(target=self._proc_thread)
        self._thread_proc.setDaemon(True)
        self._thread_proc.start()

    def close(self):
        self.serial.close()
        # self.join()
        self._thread_input = None

    def reopen(self):
        self.serial.timeout = .25
        # time.sleep(.1)
        self.serial.reset_input_buffer()
        self.close()
        time.sleep(1.5)
        self.serial.timeout = 0
        self.open(self.serial.port, self.serial.baudrate)

    def join(self, timeout=None):
        if self._thread_input is None or not self._thread_input.isAlive():
            return True

        self._thread_input.join(timeout)
        return not self._thread_input.isAlive()

    def _write(self, code, data):
        if self.serial is not None:
            self._write_q.send((code, data))

        elif self.write is not None:
            self.write(Serf.encode(code, data))
        else:
            print("no output method: code=0x{:02X} len={}".format(code, len(data)), file=sys.stderr)

    def _write_thread(self):
        for code, data in self._write_q.recv():
            try:
                self.serial.write(Serf.encode(code, data))

                if not self.serial.isOpen():
                    break
            except IOError:
                continue

    def process(self, code, data):
        for cmd in self.cmds:
            if cmd.response == code:
                break
        else:
            warn(f"received unknown command code 0x{code:02X}")
            return

        if hasattr(cmd, 'sync'):
            cmd.sync.process(cmd.decode(data))
        else:
            self._proc_q.send((cmd.handler, cmd.decode, data))

    def _proc_thread(self):
        for handler, decode, data in self._proc_q.recv():
            handler(decode(data))

    @staticmethod
    def on_frame(code, data):
        print(f"unhandled: code=0x{code:02X} len={len(data)}", file=sys.stderr)

    def _input_thread(self):
        try:
            data = bytearray()

            while self.serial.isOpen():
                in_data = self.serial.read()

                if not len(in_data):
                    continue

                data.extend(in_data)

                if 0 not in data:
                    continue

                idx = data.index(0)

                result = Serf.decode(data[:idx])

                if result is not Serf.SERF_DECODE_ERROR:
                    self.process(*result)

                data = bytearray()

        except IOError:
            pass


class WaitSync:
    multi = False
    handle = None
    writer = None
    q = None

    def __init__(self, handle, writer, multi):
        self.handle = handle
        self.writer = writer
        self.multi = multi
        self.q = AsyncQ()

        if multi:
            self.write_wait = self.write_wait_multi
        else:
            self.write_wait = self.write_wait_normal

        if writer is None:
            self.writer = lambda *a, **k: None
            threading.Thread(target=self.__passive_wait, daemon=True).start()

    def __passive_wait(self):
        while 1:
            for item in self.q.recv():
                if self.handle:
                    self.handle(item)

    def process(self, data):
        self.q.send(data)

    def write_wait_multi(self, *args, **kwds):
        self.writer(*args, **kwds)

        for item in self.q.recv():
            if item is not None:
                yield self.handle(item)
            else:
                break

    def write_wait_normal(self, *args, **kwds):
        self.writer(*args, **kwds)
        return tuple(self.q.recv(once=True))[0]
