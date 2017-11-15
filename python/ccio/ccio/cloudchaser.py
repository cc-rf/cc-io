#!/usr/bin/env python2
"""Cloud Chaser Support Library
"""
from __future__ import print_function
import os
import sys
import struct
import time
import random
import threading
import traceback
import cleanup
from serf import Serf
from stats import Stats


class CloudChaser(Serf):
    CODE_ID_ECHO = 0
    CODE_ID_STATUS = 1
    CODE_ID_SEND = 2
    CODE_ID_RECV = 3
    CODE_ID_RESET = 9
    CODE_ID_UART = 26
    CODE_ID_RAINBOW = 29

    RESET_MAGIC = 0xD1E00D1E

    NMAC_SEND_DGRM = 0
    NMAC_SEND_MESG = 1
    NMAC_SEND_TRXN = 2
    NMAC_SEND_STRM = 3

    __CODE_SEND_WAIT = 1

    def __init__(self, stats=None, handler=None):
        super(CloudChaser, self).__init__()
        
        self.stats = stats
        self.handler = handler

        self.add(
            name='echo',
            code=CloudChaser.CODE_ID_ECHO,
            encode=lambda mesg: struct.pack("<%is" % (len(mesg) + 1), mesg + '\x00'),
            decode=lambda data: struct.unpack("<%is" % len(data), data),
            handle=lambda mesg: sys.stdout.write(mesg)
        )

        self.add(
            name='reset',
            code=CloudChaser.CODE_ID_RESET,
            encode=lambda: struct.pack("<I", CloudChaser.RESET_MAGIC)
        )

        self.add(
            name='status',
            code=CloudChaser.CODE_ID_STATUS,
            decode=lambda data: struct.unpack("<IQIHIIIIII%is" % (len(data) - 42), data)[:-1],
            handle=self.handle_status,
            response=CloudChaser.CODE_ID_STATUS
        )

        self.add(
            name='recv',
            code=CloudChaser.CODE_ID_RECV,
            decode=lambda data: struct.unpack("<HHHHbB%is" % (len(data) - 10), data),
            handle=self.handle_recv
        )

        self.add(
            name='send',
            code=CloudChaser.CODE_ID_SEND,
            encode=lambda typ, dest, data, flag=0, node=0: struct.pack(
                "<BBHHH%is" % len(data), typ & 0xFF, (flag & ~CloudChaser.__CODE_SEND_WAIT) & 0xFF, node & 0xFFFF, dest & 0xFFFF, len(data), data
            )
        )

        self.add(
            name='send_wait',
            code=CloudChaser.CODE_ID_SEND,
            encode=lambda typ, dest, data, flag=0, node=0: struct.pack(
                "<BBHHH%is" % len(data), typ & 0xFF, (flag | CloudChaser.__CODE_SEND_WAIT) & 0xFF, node & 0xFFFF,
                dest & 0xFFFF, len(data), data
            ),
            decode=lambda data: struct.unpack("<HI", data),
            response=CloudChaser.CODE_ID_SEND
        )

        self.add(
            name='uart',
            code=CloudChaser.CODE_ID_UART,
            encode=lambda data, code=0x00: struct.pack("<B", code & 0xFF) + data,
            decode=lambda data: struct.unpack("<B%is" % (len(data) - 1), data),
            handle=self.handle_uart
        )

        self.add(
            name='rainbow',
            code=CloudChaser.CODE_ID_RAINBOW
        )

    def __str__(self):
        return "cc@{}".format(self.port)

    def reset(self, reopen=True):
        self.io.reset()

        if reopen:
            self.reopen()
        else:
            self.close()

    def handle_status(self, version, serial, uptime, node, recv_count, recv_bytes, recv_error, send_count, send_bytes, send_error):
        print("Cloud Chaser {:016X}@{:04X} up={}s rx={}/{}/{} tx={}/{}/{}".format(
            serial, node, uptime // 1000, recv_count, recv_bytes, recv_error, send_count, send_bytes, send_error
        ), file=sys.stderr)

    def handle_recv(self, node, peer, dest, size, rssi, lqi, data):
        if self.stats is not None:
            self.stats.lock()
            if not self.stats.recv_count:
                self.stats.recv_time = time.time()
    
            self.stats.recv_size += len(data)
            self.stats.recv_count += 1
            self.stats.rssi_sum += rssi
            self.stats.lqi_sum += lqi
            self.stats.unlock()

        if self.handler is not None:
            self.handler(self, node, peer, dest, rssi, lqi, data)

    def handle_uart(self, code, data):
        pass
