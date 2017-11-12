#!/usr/bin/env python2
"""Cloud Chaser UDP Forwarding Helper.
"""
from __future__ import print_function
import os
import sys
import struct
import argparse
import time
import random
import threading
import traceback
import socket
import ipaddress
from ccio import CloudChaser, cleanup


class Udp(object):
    addr = ("0.0.0.0", 0)
    dest = None
    sock = None

    def __init__(self, addr, port, sender=False, iface=None):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 16384)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16384)

        addr_ip = socket.gethostbyname(addr)
        is_multicast = ipaddress.ip_address(unicode(addr_ip)).is_multicast

        if iface is not None:
            iface_ip = socket.gethostbyname(iface)
        else:
            iface_ip = "0.0.0.0"

        if not sender:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            self.sock.bind((addr, port))
        else:
            self.dest = (addr_ip, port)

            if is_multicast:
                self.sock.bind((addr, 0))
            else:
                self.sock.bind((iface_ip, 0))

        self.addr = self.sock.getsockname()

        if is_multicast:
            mreq = socket.inet_aton(addr_ip) + socket.inet_aton(iface_ip)
            self.sock.setsockopt(socket.SOL_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        elif not sender and iface is not None:
            print("<udp@{}> ignoring interface".format(self))

    def __str__(self):
        return "{}:{}".format(*self.addr)

    def dest_str(self):
        return "{}:{}".format(*self.dest)


class Forward(object):
    QUEUE_MAX_LEN = 2048

    udp_rx = None
    udp_tx = None
    sem_prod = None
    sem_cons = None
    thr_rx = None
    thr_tx = None
    queue = None
    verbose = False

    def __init__(self, src_addr, src_port, dst_addr, dst_port, iface=None, verbose=False, handler=None):
        self.sem_prod = threading.Semaphore(Forward.QUEUE_MAX_LEN)
        self.sem_cons = threading.Semaphore(0)

        if src_port is None or src_port == -1:
            if dst_port is None:
                raise ValueError("only src or dst can specify serial port")

            self.__rxo = self.cc_rx = CloudChaser(handler=self._cc_handle)
            self.__txo = self.udp_tx = Udp(dst_addr, dst_port, sender=True)

            self.cc_rx.open(src_addr)
            self.cc_rx.io.status()

            self.thr_tx = threading.Thread(target=self._udp_send_task)

        else:
            if dst_port is not None and dst_port != -1:
                raise ValueError("src or dst must specify serial port")

            self.__rxo = self.udp_rx = Udp(src_addr, src_port, sender=False, iface=iface)
            self.__txo = self.cc_tx = CloudChaser()

            self.cc_tx.open(dst_addr)
            self.cc_tx.io.status()

            self.thr_rx = threading.Thread(target=self._udp_recv_task)

        self.queue = []
        self.verbose = verbose

        if handler is not None:
            self.process = handler

    def __str__(self):
        if self.udp_tx is not None:
            return "{} -> {}".format(self.__rxo, self.udp_tx.dest_str())
        else:
            return "{} -> {}".format(self.__rxo, self.__txo)

    def start(self):
        if self.thr_rx is not None:
            self.thr_rx.start()
        if self.thr_tx is not None:
            self.thr_tx.start()

    def _cc_handle(self, cc, node, peer, dest, rssi, lqi, data):
        if self.verbose:
            print("<{:04X}> ({}) {}".format(
                peer, len(data), " ".join("{:02X}".format(ord(ch)) for ch in data)
            ))

        self.sem_prod.acquire()
        self.queue.append(data)
        self.sem_cons.release()

    def _udp_recv_task(self):
        while 1:
            self.sem_prod.acquire()
            data, addr = self.udp_rx.sock.recvfrom(4096)

            if self.verbose:
                print("[{}:{}] ({}) {}".format(addr[0], addr[1], len(data), " ".join("{:02X}".format(ord(b)) for b in data)), file=sys.stderr)

            try:
                data = self.process(data)
            except:
                traceback.print_exc()
                data = None

            if data:
                if type(data) not in (list, tuple):
                    data = (data,)

                for message in data:
                    self.cc_tx.io.send(CloudChaser.NMAC_SEND_STRM, 0x0000, message)

    def _udp_send_task(self):
        while 1:
            self.sem_cons.acquire()
            data = self.queue.pop(0)
            self.sem_prod.release()

            try:
                data = self.process(data)
            except:
                traceback.print_exc()
                data = None

            if data:
                if type(data) not in (list, tuple):
                    data = (data,)

                for message in data:
                    self.udp_tx.sock.sendto(message, self.udp_tx.dest)

    def process(self, data):
        return data


def main(args):
    if not args.out_port:
        args.out_port = args.port

    fwd = Forward(args.input, args.port, args.out, args.out_port, args.iface, args.verbose)

    print(fwd)
    fwd.start()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-I', '--iface', metavar='ADDR', required=False, help='source interface address (NOT name!)')
    parser.add_argument('-i', '--input', metavar='IN', required=True, help='source address or serial port')
    parser.add_argument('-p', '--port', metavar='PORT', type=int, default=-1, help='source port')
    parser.add_argument('-o', '--out', metavar='OUT', required=True, help='destination address or serial port')
    parser.add_argument('-P', '--out-port', metavar='PORT', type=int, default=-1, help='destination port')
    parser.add_argument('-v', '--verbose', action='store_true', help='verbose output')

    cleanup.install(lambda: os._exit(0))

    try:
        main(parser.parse_args())

    except KeyboardInterrupt:
        pass

    except SystemExit:
        raise

    except:
        traceback.print_exc()
        sys.exit(1)

    sys.exit(0)
