"""Serial Framed RF Device Communication Protocol
"""
import sys
import struct
import time
import threading
import traceback

from . import cobs
from .util import adict


class Serf(object):
    SERF_CODE_PROTO_M   = 0b11100000
    SERF_CODE_PROTO_VAL = 0b10100000
    SERF_CODE_M         = 0b00011111
    SERF_DECODE_ERROR   = (0, None)

    def __init__(self, write=None):
        self.io = adict()
        self.codes = {}
        self.serial = None
        self._sync = {}
        self._thread_input = None
        self._thread_write = None
        self._thread_proc = None
        self._write_queue = []
        self._write_sync = threading.Semaphore(0)
        self._proc_queue = []
        self._proc_sync = threading.Semaphore(0)
        self.write = write
        self.port = None

    def add(self, name, code, encode=None, decode=None, handle=None, response=None, multi=False):
        if encode is None:
            encode = lambda *args, **kwds: bytes()

        if decode is None:
            decode = lambda data: (code, data)

        if handle is None:
            handle = self.on_frame

        self.codes[code] = (encode, decode, handle)

        if response is None:
            self.io[name] = lambda *args, **kwds: self._write(code, encode(*args, **kwds))

        else:
            if handle == self.on_frame:
                handle = lambda *args: args

            _writer = lambda *args, **kwds: self._write(code, encode(*args, **kwds))

            _sync = WaitSync(handle, _writer, multi)
            self._sync[response] = _sync

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
        try:
            self.serial.close()
            # self.join()
            self._thread_input = None
        except:
            pass

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

        try:
            self._thread_input.join(timeout)
            return not self._thread_input.isAlive()

        except:
            return False

    def send(self, code, *args, **kwds):
        encode = self.codes[code][0]
        self._write(code, encode(*args, **kwds))

    def _write(self, code, data):
        if self.serial is not None:
            self._write_queue.append((code, data))
            self._write_sync.release()

        elif self.write is not None:
            self.write(Serf.encode(code, data))
        else:
            print("no output method: code=0x{:02X} len={}".format(code, len(data)), file=sys.stderr)

    def _write_thread(self):
        while self.serial.isOpen():
            self._write_sync.acquire()
            code, data = self._write_queue.pop(0)

            try:
                self.serial.write(Serf.encode(code, data))

            except KeyboardInterrupt:
                sys.exit(0)

            except IOError:
                continue

            except:
                traceback.print_exc()
                break

    def process(self, code, data):
        encode, decode, handler = self.codes.get(code, (None, lambda data: (code, data), self.on_frame))

        sync = self._sync.get(code, None)

        if sync is not None:
            sync.process(decode(data))
        else:
            self._proc_queue.append((handler, decode, data))
            self._proc_sync.release()

    def _proc_thread(self):
        while 1:
            self._proc_sync.acquire()
            handler, decode, data = self._proc_queue.pop(0)

            try:
                handler(*decode(data))

            except KeyboardInterrupt:
                sys.exit(0)
            except:
                traceback.print_exc()

    def on_frame(self, code, data):
        print("unhandled: code=0x{:02X} len={}".format(code, len(data)), file=sys.stderr)

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
                    try:
                        self.process(*result)
                    except:
                        traceback.print_exc()

                data = bytearray()

        except KeyboardInterrupt:
            sys.exit(0)

        except IOError:
            pass

        except:
            traceback.print_exc()


class WaitSync(object):
    sem = None
    multi = False
    result = []
    handle = None
    writer = None
    done = False

    def __init__(self, handle, writer, multi):
        self.sem = threading.Semaphore(0)
        self.handle = handle
        self.writer = writer
        self.multi = multi
        self.result = []

        if multi:
            self.write_wait = self.write_wait_multi
        else:
            self.write_wait = self.write_wait_normal

    def process(self, data):
        if data is not None:
            if not self.multi:
                self.result = data
                self.done = True
            else:
                self.result.append(data)

        else:
            self.done = True

        self.sem.release()

    def write_wait_multi(self, *args, **kwds):
        self.result = []
        self.done = False
        self.writer(*args, **kwds)

        while 1:
            self.sem.acquire()

            result = self.result
            self.result = []

            for item in result:
                yield self.handle(*item)

            if self.done:
                break

    def write_wait_normal(self, *args, **kwds):
        self.result = []
        self.done = False
        self.writer(*args, **kwds)
        self.sem.acquire()
        res = self.result
        self.result = None
        res = self.handle(*res)
        return res[0] if len(res) == 1 else res
