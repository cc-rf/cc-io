#!/usr/bin/env python2
"""Basic ArtNet server.
"""
from __future__ import print_function

import math
import pickle
import struct
import sys
import socket
import threading

ADDR_DEFAULT = "127.0.0.1"
PORT_DEFAULT = 6454
RECV_BUFFER_SIZE = 16384


class ArtnetServer(object):
    addr = ("0.0.0.0", 0)
    sock = None
    cc = None
    sequence = []
    smin = 100000

    def __init__(self, cc, addr=ADDR_DEFAULT, port=PORT_DEFAULT):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, RECV_BUFFER_SIZE)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self.sock.bind((addr, port))
        self.addr = self.sock.getsockname()
        self.thr_rx = threading.Thread(target=self._recv_task)
        self.cc = cc
        self.sequence = {}

    def __str__(self):
        return "{}:{}".format(*self.addr)

    def start(self):
        self.thr_rx.start()

    def join(self):
        self.thr_rx.join()

    def _recv_task(self):
        while 1:
            data, addr = self.sock.recvfrom(RECV_BUFFER_SIZE)
            # print("[{}:{}] {}".format(addr[0], addr[1], " ".join("{:02X}".format(ord(b)) for b in data)), file=sys.stderr)
            self.handle(data)

    def handle(self, data):
        MAX_BUFFER_ARTNET = 530
        ART_NET_ID = 'Art-Net\0'
        ART_DMX = 0x5000

        hdr, op, data = struct.unpack("<%isH%is" % (len(ART_NET_ID), len(data) - len(ART_NET_ID) - 2), data)

        if hdr != ART_NET_ID:
            print("bad header")
            return

        if op == ART_DMX:
            # [0] == 0x00 [1] == 0x0E
            seq = struct.unpack("<B", data[2])[0]
            univ = struct.unpack("<H", data[4:6])[0]
            dmxlen = struct.unpack("<H", data[6:8])[0]
            self.handle_dmx(seq, univ, data[8:8+dmxlen])

        else:
            print("unknown op: 0x{:02X}".format(op))

    def handle_dmx(self, seq, universe, data):
        if not universe:
            return

        mask = 1 << (universe - 1)

        # print("seq: {} univ: {} dlen: {}".format(seq, universe, len(data)))

        colors = []

        while len(data) >= 3:
            colors.append(struct.unpack("<BBB", data[:3]))
            data = data[3:]

        if len(colors):
            # if universe not in self.sequence:
            #     self.sequence[universe] = []
            #
            # self.sequence[universe].append(colors)
            # slen = len(self.sequence[universe])

            self.cc.io.led(mask, colors)

            # if slen > 3:
            #
            #     for idx in range(slen):
            #         idxb = (idx - 1) % slen
            #         diff = ArtnetServer.diff_colors(self.sequence[universe][idx], self.sequence[universe][idxb])
            #
            #         if diff < self.smin:
            #             self.smin = diff
            #             print("u{} slen: {}\tidx={}\tidxb={}\tdiff={}".format(universe, slen, idx, idxb, diff))
            #
            #             if universe == 1 and diff < 15:
            #                 print("saving")
            #                 looped = self.sequence[universe][:idxb + 1] + self.sequence[universe][idx:]
            #                 pickle.dump(looped, file('loop1.dat', 'w'))
            #                 sys.exit(1)

    @staticmethod
    def diff_colors(ca, cb):
        diff = 0.0

        for cai, cbi in zip(ca, cb):
            diff += sum(math.sqrt(abs(cbc**2 - cac**2)) for cac, cbc in zip(cai, cbi))

        diff /= min(len(ca), len(cb))
        return diff

