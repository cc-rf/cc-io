#!/usr/bin/env python2
"""Serial Framed RF Device Communication Protocol
"""
import os
import random
import sys
import struct
import time
import cobs
import threading
import traceback


class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        self.__dict__ = self


class Serf(object):
    SERF_CODE_PROTO_M   = 0b11100000
    SERF_CODE_PROTO_VAL = 0b10100000
    SERF_CODE_M         = 0b00011111
    SERF_DECODE_ERROR   = (0, None)

    def __init__(self, write=None):
        self.io = AttrDict()
        self.codes = {}
        self.serial = None
        self._sync = {}
        self._thread_input = None
        self.write = write

    def add(self, name, code, encode=None, decode=None, handle=None, response=None):
        if encode is None:
            encode = lambda *args, **kwds: ''

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

            sem = threading.Semaphore(0)
            _sync = [None, sem]
            self._sync[response] = _sync

            def _write_wait(*args, **kwds):
                _sync[0] = False
                self._write(code, encode(*args, **kwds))
                sem.acquire()
                res = _sync[0]
                _sync[0] = None
                return handle(*res)

            self.io[name] = _write_wait

    @staticmethod
    def encode(code, data):
        if (code & Serf.SERF_CODE_M) != code:
            print >> sys.stderr, "warning: code 0x%02X truncated to 0x%02X" % (code, code & Serf.SERF_CODE_M)

        frame = struct.pack("<B%is" % len(data), Serf.SERF_CODE_PROTO_VAL | (code & Serf.SERF_CODE_M), data)
        frame = cobs.cobs_encode(frame) + '\0'
        return frame

    @staticmethod
    def decode(data):
        if len(data) <= 1:
            return Serf.SERF_DECODE_ERROR

        data = cobs.cobs_decode(data)

        if not len(data):
            print >> sys.stderr, "serf: empty data"
            return Serf.SERF_DECODE_ERROR

        if (ord(data[0]) & Serf.SERF_CODE_PROTO_M) != Serf.SERF_CODE_PROTO_VAL:
            print >> sys.stderr, "serf: bad proto val"
            return Serf.SERF_DECODE_ERROR

        return ord(data[0]) & Serf.SERF_CODE_M, data[1:]

    def open(self, tty, baud=115200):
        if self.serial is not None:
            self.close()
        else:
            import serial
            # self.serial = serial.Serial(timeout=0.01)
            self.serial = serial.Serial()

        self.serial.port = tty
        self.serial.baudrate = baud
        self.serial.open()
        self._thread_input = threading.Thread(target=self._input_thread)
        self._thread_input.setDaemon(True)
        self._thread_input.start()

    def close(self):
        try:
            self.serial.close()
            self.join()
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
            self.serial.write(Serf.encode(code, data))
        elif self.write is not None:
            self.write(Serf.encode(code, data))
        else:
            print >>sys.stderr, "no output method: code=0x%02X len=%u" % (code, len(data))

    def on_frame(self, code, data):
        print >>sys.stderr, "unhandled: code=0x%02X len=%u" % (code, len(data))

    def process(self, code, data):
        encode, decode, handler = self.codes.get(code, (None, lambda data: (code, data), self.on_frame))

        sync = self._sync.get(code, None)

        if sync is not None and sync[0] is False:
            sync[0] = decode(data)
            sync[1].release()
        else:
            handler(*decode(data))

    def _input_thread(self):
        try:
            data = ''

            while self.serial.isOpen():
                in_data = self.serial.read()

                if not in_data or not len(in_data):
                    continue

                data = data + in_data

                if '\0' not in data:
                    continue

                idx = data.index('\0')

                result = Serf.decode(data[:idx])

                if result is not Serf.SERF_DECODE_ERROR:
                    try:
                        self.process(*result)
                    except:
                        traceback.print_exc()

                data = ''

        except KeyboardInterrupt:
            sys.exit(0)

        except IOError:
            pass

        except:
            traceback.print_exc()

