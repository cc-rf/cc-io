#!/usr/bin/env python2
"""Basic ArtNet server.
"""
from __future__ import print_function
import sys
import socket
import threading

ADDR_DEFAULT = "0.0.0.0"
PORT_DEFAULT = 6454
RECV_BUFFER_SIZE = 16384


class ArtnetServer(object):
    addr = ("0.0.0.0", 0)
    sock = None
    cc = None

    def __init__(self, cc, addr=ADDR_DEFAULT, port=PORT_DEFAULT):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, RECV_BUFFER_SIZE)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self.sock.bind((addr, port))
        self.addr = self.sock.getsockname()
        self.thr_rx = threading.Thread(target=self._recv_task)
        self.cc = cc

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
        # Lifted from https://github.com/bbx10/artnet-unicorn-hat/blob/master/artnet-server.py
        if (len(data) > 18) and (data[0:8] == "Art-Net\x00"):
            rawbytes = map(ord, data)
            opcode = rawbytes[8] + (rawbytes[9] << 8)
            protocolVersion = (rawbytes[10] << 8) + rawbytes[11]
            if (opcode == 0x5000) and (protocolVersion >= 14):
                sequence = rawbytes[12]
                physical = rawbytes[13]
                sub_net = (rawbytes[14] & 0xF0) >> 4
                universe = rawbytes[14] & 0x0F
                net = rawbytes[15]
                rgb_length = (rawbytes[16] << 8) + rawbytes[17]
                # print("seq %d phy %d sub_net %d uni %d net %d len %d" % (sequence, physical, sub_net, universe, net, rgb_length))
                idx = 18
                colors = []
                while idx < (rgb_length + 18):
                    r = rawbytes[idx]
                    idx += 1
                    g = rawbytes[idx]
                    idx += 1
                    b = rawbytes[idx]
                    idx += 1
                    colors.append((r, g, b))

                self.cc.io.led(colors)

