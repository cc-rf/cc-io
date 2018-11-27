"""Serial Framed RF Device Communication Protocol
"""
import sys
import os
import struct
import time
import socket
import pickle
import traceback
from threading import Thread, Event, Lock
import fcntl
from warnings import warn

from . import cobs
from .util import adict, oadict
from .asyncq import AsyncQ


class Serf:
    SERF_CODE_PROTO_M   = 0b11100000
    SERF_CODE_PROTO_VAL = 0b10100000
    SERF_CODE_M         = 0b00011111
    SERF_DECODE_ERROR   = (0, None)

    cmds = None

    def __init__(self):
        self.io = adict()
        self.cmds = oadict()
        self.serial = None
        self._sync = {}
        self._thread_input = None
        self._thread_write = None
        self._thread_proc = None
        self._write_q = AsyncQ(size=1024)
        self._write_e = Event()
        self._proc_q = AsyncQ()
        self.port = None

    def add(self, name, code=None, encode=None, decode=None, handle=None, response=None, multi=False):
        if encode is None:
            encode = lambda *args, **kwds: bytes()

        if decode is None:
            decode = lambda data: (code, data)

        if handle is None:
            handle = self.handle_noop

        cmd = adict(
            name=name, code=code, response=response,
            encode=encode, decode=decode, multi=multi,
            handle=handle
        )

        self.cmds[name] = cmd

        if response is None:
            self.io[name] = lambda *args, **kwds: self._write(cmd.code, cmd.encode(*args, **kwds))

        else:
            _writer = None if cmd.code is None else \
                lambda *a, **k: self._write(cmd.code, cmd.encode(*a, **k))

            _sync = WaitSync(handle, _writer, multi)
            cmd.sync = _sync

            self.io[name] = _sync.write_wait

    @staticmethod
    def encode(code, data):
        if (code & Serf.SERF_CODE_M) != code:
            print("warning: code 0x{:02X} truncated to 0x{:02X}".format(code, code & Serf.SERF_CODE_M), file=sys.stderr)

        size = cobs.cobs_encode(struct.pack("<BI", 0xFF, len(data))) + b'\0' if len(data) else b''

        frame = struct.pack(f"<B{len(data)}s", Serf.SERF_CODE_PROTO_VAL | (code & Serf.SERF_CODE_M), data)
        frame = size + cobs.cobs_encode(frame) + b'\0'
        # frame = cobs.cobs_encode(frame) + b'\0'

        return frame

    @staticmethod
    def decode(data):
        in_len = len(data)

        # print(f"raw:", len(data), ' '.join(f"{v:02X}" for v in data))

        if in_len <= 1:
            print(f"serf: data too small ({in_len})", file=sys.stderr)
            return Serf.SERF_DECODE_ERROR

        data = cobs.cobs_decode(data)

        if len(data) < 1:
            print(f"serf: decoded too small ({in_len}->{len(data)})", file=sys.stderr)
            return Serf.SERF_DECODE_ERROR

        # print(f"decoded:", len(data), ' '.join(f"{v:02X}" for v in data))

        code = data[0]

        if (code & Serf.SERF_CODE_PROTO_M) != Serf.SERF_CODE_PROTO_VAL:
            print(f"serf: bad code 0x{code:02X}", file=sys.stderr)
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

        fcntl.flock(self.serial.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        self._thread_input = Thread(target=self._input_thread, daemon=True)
        self._thread_input.start()

        self._thread_write = Thread(target=self._write_thread, daemon=True)
        self._thread_write.start()

        self._thread_proc = Thread(target=self._proc_thread, daemon=True)
        self._thread_proc.start()

    def close(self, timeout=None):
        if self._thread_proc:
            self._proc_q.send(None)
            self._thread_proc.join(timeout)
            self._thread_proc = None

        if self._thread_write:
            self._write_q.send(None)
            self._thread_write.join(timeout)
            self._thread_write = None

        if self.serial is not None:
            fcntl.flock(self.serial.fileno(), fcntl.LOCK_UN)
            self.serial.close()
            self.serial = None

        self._thread_input = None

        return not self._thread_write.isAlive() if self._thread_write else True

    def reopen(self):
        self.serial.timeout = .25
        # time.sleep(.1)
        self.serial.reset_input_buffer()
        self.close()
        time.sleep(1.5)
        self.serial.timeout = 0
        self.open(self.serial.port, self.serial.baudrate)

    def join(self, timeout=None):
        if self._thread_write and self._thread_write.isAlive():
            self._thread_write.join(timeout=timeout)
            return self._thread_write.isAlive()

        return False

    def flush(self):
        self._write_q.send((None, b'\0\0'))

    def _write(self, code, data):
        if self.serial is not None:
            # self.flush()
            self._write_q.send((code, data))
        else:
            print("no output method: code=0x{:02X} len={}".format(code, len(data)), file=sys.stderr)

    def _write_thread(self):
        for qi in self._write_q.recv():
            if qi is None:
                break

            code, data = qi

            try:
                self.serial.write(Serf.encode(code, data) if code is not None else data)

                if not self.serial.isOpen():
                    break

                # self.serial.flush()

            except IOError:
                continue

    def process(self, code, data):
        for cmd in self.cmds.values():
            if cmd.response == code:
                break
        else:
            print(f"unknown code 0x{code:02X}", file=sys.stderr)
            return

        if hasattr(cmd, 'sync'):
            cmd.sync.process(cmd.decode(data))
        else:
            self._proc_q.send((cmd.handler, cmd.decode, data))

    def _proc_thread(self):
        for qi in self._proc_q.recv():

            if qi is None:
                break

            handler, decode, data = qi

            handler(decode(data))

    @staticmethod
    def handle_noop(rslt):
        return rslt

    def _input_thread(self):
        try:
            data = bytearray()

            while self.serial and self.serial.isOpen():
                in_data = self.serial.read()

                if in_data is None or not len(in_data):
                    continue

                data.extend(in_data)

                if 0 not in data:
                    continue

                idx = data.index(0)

                result = Serf.decode(data[:idx])

                if result is not Serf.SERF_DECODE_ERROR:
                    self.process(*result)

                data = bytearray()

        except (IOError, TypeError):
            pass


class WaitSync:
    handle = None
    writer = None
    multi = False
    q = None
    lock = None

    def __init__(self, handle, writer, multi):
        self.handle = handle
        self.writer = writer
        self.multi = multi
        self.q = AsyncQ()
        self.lock = Lock()

        if multi:
            self.write_wait = self.write_wait_multi
        else:
            self.write_wait = self.write_wait_normal

        if writer is None:
            self.writer = lambda *a, **k: None
            Thread(target=self.__passive_wait, daemon=True).start()

    def __passive_wait(self):
        while 1:
            for item in self.q.recv():
                if self.handle:
                    self.handle(item)

    def process(self, data):
        self.q.send(data)

    def write_wait_multi(self, *args, **kwds):
        with self.lock:
            self.writer(*args, **kwds)

            for item in self.q.recv():
                if item is not None:
                    yield self.handle(item)
                else:
                    break

    def write_wait_normal(self, *args, **kwds):
        with self.lock:
            self.writer(*args, **kwds)
            return tuple(self.q.recv(once=True))[0]


class SerfClient(Serf):
    sock = None
    __handlers_installed = False

    def __init__(self):

        self.path = None

        super(SerfClient, self).__init__()

    def open(self, path: str):
        if not path.startswith("unix://"):
            raise ValueError("only unix sockets supported")

        self.path = path.replace("unix://", "", 1)

        if not self.__handlers_installed:
            self.__handlers_installed = True

            for cmd in self.cmds.values():

                def writer(name):
                    return lambda *a, **k: self.__write(name, a, k)

                if cmd.response and cmd.code:
                    cmd.sync.writer = writer(cmd.name)
                else:
                    self.io[cmd.name] = writer(cmd.name)

        try:
            self.sock: socket.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

            self.sock.connect(self.path)

            Thread(target=self.__handle_conn, daemon=True).start()

        except Exception:
            self.close()
            raise

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None

    def __write(self, name, args, kwds):
        self.sock.sendall(pickle.dumps((name, args, kwds)))

    def __handle_conn(self):
        while self.sock:
            try:
                data = self.sock.recv(0x10000)

                obj = pickle.loads(data)

                assert type(obj) is tuple and len(obj) == 2 or len(obj) == 3

                command, rslt, error = None, None, None
                code = None

                if len(obj) == 3:
                    command, rslt, error = obj

                    assert type(command) is str and error is None or type(error) is tuple
                else:
                    code, rslt = obj

                    assert type(code) is int and code

            except (pickle.UnpicklingError, TypeError, ValueError, AssertionError) as exc:
                print("serf-client:", exc, file=sys.stderr)
                break

            except (IOError, EOFError):
                print("connection closed.", file=sys.stderr)
                break

            if code:
                for cmd in self.cmds.values():
                    if cmd.response == code:
                        break
                else:
                    print(f"serf-client: invalid response code {code}", file=sys.stderr)
                    continue

                if hasattr(cmd, 'sync'):
                    cmd.sync.process(rslt)
                else:
                    self._proc_q.send((cmd.handler, lambda d: d, data))

                continue

            cmd = self.cmds.get(command)

            if not cmd or command not in self.io:
                print(f"serf-client: invalid command {command}", file=sys.stderr)
                continue

            if error:
                self.sock.close()
                SerfServer.reraise(*error)
                break

            if cmd.response:
                cmd.sync.process(rslt)

        if self.sock:
            self.close()
            os._exit(0)  # TODO: Find better way to propagate closure forcefully?


class SerfServer(Serf):
    sock = None
    clients = None
    __handlers_installed = False

    def __init__(self):
        self.clients = []
        self.path = None

        super(SerfServer, self).__init__()

    def open(self, tty, path):
        if not path.startswith("unix://"):
            raise ValueError("only unix sockets supported")

        self.path = path.replace("unix://", "", 1)

        super(SerfServer, self).open(tty)

        if not self.__handlers_installed:
            self.__handlers_installed = True

            for cmd in self.cmds.values():
                if cmd.response and cmd.handle != self.handle_noop:
                    cmd.handle_orig = cmd.handle

                    def handler(c):
                        return lambda r: self.__handle_input(c, r)

                    if cmd.code is None:
                        cmd.sync.handle = handler(cmd)
                    else:
                        cmd.handle = handler(cmd)

        try:
            if os.path.exists(self.path):
                os.unlink(self.path)

            self.sock: socket.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

            self.sock.bind(self.path)

            Thread(target=self.__listen, daemon=True).start()

        except Exception:
            self.close()
            raise

    def close(self, timeout=None):
        if self.sock:
            self.sock.close()
            self.sock = None

        if os.path.exists(self.path):
            os.unlink(self.path)

        super(SerfServer, self).close(timeout=timeout)

    def __handle_input(self, cmd, rslt):

        for conn in self.clients:
            try:
                conn.sendall(pickle.dumps((cmd.response, rslt)))
            except IOError:
                pass

        cmd.handle_orig(rslt)

    def __listen(self):
        self.sock.listen(1)

        while self.sock:
            conn, addr = self.sock.accept()

            Thread(target=self.__handle_client, args=(conn,), daemon=True).start()

    def __handle_client(self, conn: socket.socket):
        try:
            self.clients.append(conn)

            while self.sock:
                try:
                    data = conn.recv(0x10000)

                    obj = pickle.loads(data)

                    assert type(obj) is tuple and tuple(map(type, obj)) == (str, tuple, dict)

                    command, args, kwds = obj

                except (pickle.UnpicklingError, TypeError, ValueError, AssertionError) as exc:
                    print("serf-server:", exc, file=sys.stderr)
                    break

                except (IOError, EOFError):
                    conn.close()
                    break

                cmd = self.cmds.get(command)

                if not cmd or command not in self.io:
                    print(f"serf-server: invalid command {command}", file=sys.stderr)
                    continue

                rslt = None
                error = None

                try:
                    rslt = self.io[command](*args, **kwds)

                except Exception:
                    typ, val, tb = sys.exc_info()
                    tb = traceback.format_tb(tb)
                    error = typ, val, tb

                if cmd.response or error:
                    conn.sendall(pickle.dumps((command, rslt, error)))

        finally:
            self.clients.remove(conn)

    @staticmethod
    def reraise(typ=None, val=None, tb=None):

        if not typ:
            typ, val, tb = sys.exc_info()

        if not val:
            val = typ()

        if val.__traceback__ is not tb:
            # print("reraise tb:", tb)
            if isinstance(tb, (str, list, tuple)):
                val.__traceback__orig__ = tb
            else:
                raise val.with_traceback(tb)

        raise val


