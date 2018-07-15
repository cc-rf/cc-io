#!/usr/bin/env python2
"""Simple tests for Cloud Chaser debugging and validation.
"""
from __future__ import print_function

import pickle

from ccio import CloudChaser, Stats, cleanup
import sys
import os
import time
import argparse
import traceback
import threading
import random


pipe = [0xFFFF, 0, 0]


def recv(cc, addr, port, typ, data):
    # print("recv: addr={:02X} port={:04X} typ={:02X} len={}".format(
    #     addr, port, typ, len(data)
    # ))

    if not pipe[0] or (pipe[0] == addr and pipe[1] == port and pipe[2] == typ):
        sys.stdout.write(data)

    if port == 0x41 and typ == 0x0:
        return cc.io.send(addr, port, typ + 1, '')

    if port == 0x41 and typ == 0x1:
        cc.saved_time = time.time() - cc.saved_time
        cc.user_sync.release()
        return

    if port == 0x42 and typ == 0x3:
        cc.io.resp(addr, port, typ, 'b' * random.randrange(2, 24))

    pass


def command_recv(args, cc):
    while not cc.join(1):
        pass


def command_ping(args, cc):
    addr = int(args.param[0], 16)

    cc.user_sync = threading.Semaphore(0)
    cc.saved_time = time.time()
    cc.io.send(addr, 0x41, 0x0, '')
    cc.user_sync.acquire()

    print("ping time={:.3f}".format(cc.saved_time))


def command_send(args, cc):
    # while 1:
    #     cc.io.send(0x0000, 0x42, 0x3, '')
    #     time.sleep(0.500)

    # print("trxn", list(cc.io.trxn(0x4BF2, 0x42, 0x3, 2000, 'hi' * 16)))

    while 1:
        # rslt = list(cc.io.trxn(0x4BF2, 0x42, 0x3, 5000, 'a' * random.randrange(4, 113)))
        rslt = list(cc.io.trxn(0x4BF2, 0x42, 0x3, 1000, 'rgb' * 144))

        if not rslt:
            break

        # time.sleep(0.014)

    # elapsed = time.time()
    # rslt = list(cc.io.trxn(0x4BF2, 0x42, 0x3, 2000, 'rgb' * 144))
    # elapsed = time.time() - elapsed
    # print("trxn elaps={:.3f} count={}".format(elapsed, len(rslt)))

    # rslt = list(cc.io.trxn(0x0000, 0x42, 0x3, 100, 'a' * 113))
    #
    # for item in rslt:
    #     if not item or type(item) not in (list, tuple) or len(item) != 2:
    #         print("weird item: '{}'".format(item))
    #         continue
    #
    #     node, data = item
    #     print("trxn rslt node={:02X} data='{}'".format(node, data))


def command_peer(args, cc):
    node, now, peers = cc.io.peer()

    print("{:04X}: time={}".format(node, now))

    for addr, peer, last, rssi, lqi in peers:
        print("-> {:04X}/{:04X}: t={} q={} r={}".format(addr, peer, last, lqi, rssi))


def command_pipe(args, cc):
    addr, port, typ = args.param

    addr = int(addr, 16)
    port = int(port)
    typ = int(typ)

    pipe[:] = [addr, port, typ]

    while 1:
        data = sys.stdin.read(4096)

        if data:
            cc.io.send(addr, port, typ, data)


def net_evnt(cc, event, data):
    if event == CloudChaser.NET_EVNT_PEER:
        addr, action = data
        action = 'exp' if action == CloudChaser.NET_EVNT_PEER_EXP else 'set'
        print("peer: {} addr=0x{:04X}".format(action, addr))
    else:
        print("unknown event 0x{:02X}".format(event))


def command_mac_recv(args, cc):
    while not cc.join(1):
        pass


def command_mac_send(args, cc):
    while 1:
        data = 'a' * 16  # ''.join(chr(n % 256) for n in range(4))
        # data = ''.join([chr(random.randrange(0, 0xff+1)) for _ in range(random.randrange(4, 115))])
        cc.io.mac_send(CloudChaser.NMAC_SEND_MESG, 0x4BF2, data)
        # time.sleep(0.060)
        # sys.exit()


def main(args):
    stats = None

    if args.stats and args.command is not 'reset':
        stats = Stats()
        stats.start()

    cleanup.install(lambda: os._exit(0))

    cc = CloudChaser(stats=stats, handler=recv, evnt_handler=net_evnt)

    cc.open(args.device)
    mac_stat, phy_stat = cc.io.status()

    if args.command == 'status':
        sys.exit(0)

    if args.command == 'status-ll':
        
        print("mac: rx={}/{}/{} tx={}/{}/{}".format(
            mac_stat.recv.count, mac_stat.recv.size, mac_stat.recv.error,
            mac_stat.send.count, mac_stat.send.size, mac_stat.send.error
        ), file=sys.stderr)

        print("phy: rx={}/{}/{} tx={}/{}/{}".format(
            phy_stat.recv.count, phy_stat.recv.size, phy_stat.recv.error,
            phy_stat.send.count, phy_stat.send.size, phy_stat.send.error
        ), file=sys.stderr)

        sys.exit(0)

    if args.verbose:
        cc.mac_handler = print_packet

    if args.command == 'mac_recv':
        command_mac_recv(args, cc)
        sys.exit(0)

    if args.command == 'mac_send':
        command_mac_send(args, cc)
        sys.exit(0)

    if args.command == 'recv':
        command_recv(args, cc)
        sys.exit(0)

    if args.command == 'ping':
        command_ping(args, cc)
        sys.exit(0)

    if args.command == 'send':
        command_send(args, cc)
        sys.exit(0)

    if args.command == 'peer':
        command_peer(args, cc)
        sys.exit(0)

    if args.command == 'pipe':
        command_pipe(args, cc)
        sys.exit(0)

    if args.command == 'rainbow':
        cc.io.rainbow()

    if args.command == 'artnet':
        import artnet
        server = artnet.ArtnetServer(cc)
        server.start()
        server.join()
        sys.exit(0)

    if args.command == 'replay':
        infile = args.param[0]
        indata = pickle.load(file(infile, 'rb'))

        while 1:
            for colors in indata:
                cc.io.led(0x01, colors)
                time.sleep(0.04)


def print_packet(cc, node, peer, dest, rssi, lqi, data):
    print("<{:04X}> {:04X}->{:04X}: ({}) {}".format(
        node, peer, dest, len(data), " ".join("{:02X}".format(ord(ch)) for ch in data)
    ))

    # print("{:04X}->{:04X}: ({})".format(peer, dest, len(data)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--device', metavar='DEV', required=True, help='serial input device')
    parser.add_argument('-s', '--stats', action='store_true', help='show periodic rx stats')
    parser.add_argument('-v', '--verbose', action='store_true', help='verbose output')
    # parser.add_argument('-D', '--debug', action='store_true', help='debug mode')
    parser.add_argument('command', help='program command')
    parser.add_argument('param', nargs="*", help='command params')

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
