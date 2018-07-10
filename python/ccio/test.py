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
import random


def recv(cc, node, port, typ, data):
    print("recv: node={:02X} port={:04X} typ={:02X} len={}".format(
        node, port, typ, len(data)
    ))

    if port == 0x42 and typ == 0x3:
        cc.io.trxn_repl(node, port, typ, 'rgb' * 12)


def command_recv(args, cc):
    while not cc.join(1):
        pass


def command_send(args, cc):
    # cc.io.send(0x00, 0x42, 0x3, 'rgb' * 144)

    # elapsed = time.time()
    # rslt = cc.io.trxn(0x00, 0x42, 0x3, 2000, 'rgb' * 10)
    # elapsed = time.time() - elapsed
    # print("trxn elaps={:.3f} count={}".format(elapsed, len(rslt)))

    rslt = cc.io.trxn(0x00, 0x42, 0x3, 1000, 'rgb' * 144)

    for item in rslt:
        if not item or type(item) not in (list, tuple) or len(item) != 2:
            print("weird item: '{}'".format(item))
            continue

        node, data = item
        print("trxn rslt node={:02X} data='{}'".format(node, data))


def net_evnt(cc, event, data):
    if event == CloudChaser.NET_EVNT_ASSOC:
        print("assoc: node=0x{:02X}".format(data))
    elif event == CloudChaser.NET_EVNT_PEER:
        addr, node, action = data
        action = 'rem' if action == CloudChaser.NET_EVNT_PEER_REM else 'set'
        print("peer: {} addr=0x{:04X} node=0x{:02X}".format(action, addr, node))
    else:
        print("unknown event 0x{:02X}".format(event))


def command_mac_recv(args, cc):
    while not cc.join(1):
        pass


def command_mac_send(args, cc):
    while 1:
        data = 'a' * 8  # ''.join(chr(n % 256) for n in range(4))
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
    cc.io.status()

    if args.command == 'status':
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

    if args.command == 'send':
        command_send(args, cc)
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
