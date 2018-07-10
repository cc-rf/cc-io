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
    CODE_ID_MAC_SEND = 2
    CODE_ID_MAC_RECV = 3
    CODE_ID_SEND = 4
    CODE_ID_RECV = 5
    CODE_ID_TRXN = 6
    CODE_ID_TRXN_REPL = 7
    CODE_ID_EVNT = 8
    CODE_ID_RESET = 9
    CODE_ID_UART = 26
    CODE_ID_LED = 27
    CODE_ID_RAINBOW = 29

    NET_EVNT_ASSOC = 0
    NET_EVNT_PEER = 1
    NET_EVNT_PEER_SET = 0
    NET_EVNT_PEER_REM = 1

    RESET_MAGIC = 0xD1E00D1E

    NMAC_SEND_DGRM = 0
    NMAC_SEND_MESG = 1
    NMAC_SEND_TRXN = 2
    NMAC_SEND_STRM = 3

    __CODE_SEND_WAIT = 1

    def __init__(self, stats=None, handler=None, evnt_handler=None, mac_handler=None):
        super(CloudChaser, self).__init__()
        
        self.stats = stats
        self.handler = handler
        self.evnt_handler = evnt_handler
        self.mac_handler = mac_handler

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
            name='mac_recv',
            code=CloudChaser.CODE_ID_MAC_RECV,
            decode=lambda data: struct.unpack("<HHHHbB%is" % (len(data) - 10), data),
            handle=self.handle_mac_recv
        )

        self.add(
            name='mac_send',
            code=CloudChaser.CODE_ID_MAC_SEND,
            encode=lambda typ, dest, data, flag=0, addr=0: struct.pack(
                "<BBHHH%is" % len(data), typ & 0xFF, (flag & ~CloudChaser.__CODE_SEND_WAIT) & 0xFF, addr & 0xFFFF, dest & 0xFFFF, len(data), data
            )
        )

        self.add(
            name='mac_send_wait',
            code=CloudChaser.CODE_ID_MAC_SEND,
            encode=lambda typ, dest, data, flag=0, addr=0: struct.pack(
                "<BBHHH%is" % len(data), typ & 0xFF, (flag | CloudChaser.__CODE_SEND_WAIT) & 0xFF, addr & 0xFFFF,
                dest & 0xFFFF, len(data), data
            ),
            decode=lambda data: struct.unpack("<HI", data),
            response=CloudChaser.CODE_ID_MAC_SEND
        )

        self.add(
            name='send',
            code=CloudChaser.CODE_ID_SEND,
            encode=lambda node, port, typ, data: struct.pack(
                "<BHB%is" % len(data), node & 0xFF, port & 0xFFFF, typ & 0xFF, data
            )
        )

        self.add(
            name='recv',
            code=CloudChaser.CODE_ID_RECV,
            decode=lambda data: struct.unpack("<BHB%is" % (len(data) - 4), data),
            handle=self.handle_recv
        )

        def decode_trxn_stat(data):
            node, port, typ, data = struct.unpack("<BHB%is" % (len(data) - 4), data)
            # TODO: Validate/match port & type
            return None if not node else (node, data)

        self.add(
            name='trxn',
            code=CloudChaser.CODE_ID_TRXN,
            encode=lambda node, port, typ, wait, data: struct.pack(
                "<BHBI%is" % len(data), node & 0xFF, port & 0xFFFF, typ & 0xFF, wait & 0xFFFFFFFF, data
            ),
            decode=decode_trxn_stat,
            response=CloudChaser.CODE_ID_TRXN,
            multi=True
        )

        self.add(
            name='trxn_repl',
            code=CloudChaser.CODE_ID_TRXN_REPL,
            encode=lambda node, port, typ, data: struct.pack(
                "<BHB%is" % len(data), node & 0xFF, port & 0xFFFF, typ & 0xFF, data
            )
        )

        def decode_evnt(data):
            event, data = struct.unpack("<B%is" % (len(data) - 1), data)

            if event == CloudChaser.NET_EVNT_ASSOC:
                data = struct.unpack("<B", data[0])[0]
            elif event == CloudChaser.NET_EVNT_PEER:
                data = struct.unpack("<HBB", data)

            return event, data

        self.add(
            name='evnt',
            code=CloudChaser.CODE_ID_EVNT,
            decode=decode_evnt,
            handle=self.handle_evnt
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

        self.add(
            name='led',
            code=CloudChaser.CODE_ID_LED,
            encode=lambda mask, rgb: struct.pack(
                "<B%is" % len(rgb * 3), mask & 0xFF,
                ''.join(chr(c) for grb in [(g, r, b) for r, g, b in rgb] for c in grb)  # Rearrange and unroll
            )
        )

    def __str__(self):
        return "cc@{}".format(self.port)

    def reset(self, reopen=True):
        self.io.reset()

        if reopen:
            self.reopen()
        else:
            self.close()

    def handle_status(self, version, serial, uptime, macid, recv_count, recv_bytes, recv_error, send_count, send_bytes, send_error):
        print("Cloud Chaser {:016X}@{:04X} up={}s rx={}/{}/{} tx={}/{}/{}".format(
            serial, macid, uptime // 1000, recv_count, recv_bytes, recv_error, send_count, send_bytes, send_error
        ), file=sys.stderr)

    def handle_mac_recv(self, node, peer, dest, size, rssi, lqi, data):
        if self.stats is not None:
            self.stats.lock()
            if not self.stats.recv_count:
                self.stats.recv_time = time.time()
    
            self.stats.recv_size += len(data)
            self.stats.recv_count += 1
            self.stats.rssi_sum += rssi
            self.stats.lqi_sum += lqi
            self.stats.unlock()

        if self.mac_handler is not None:
            self.mac_handler(self, node, peer, dest, rssi, lqi, data)

    def handle_recv(self, node, port, typ, data):
        if self.handler is not None:
            self.handler(self, node, port, typ, data)

    def handle_evnt(self, event, data):
        if self.evnt_handler is not None:
            self.evnt_handler(self, event, data)

    def handle_uart(self, code, data):
        pass
