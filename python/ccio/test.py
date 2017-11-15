#!/usr/bin/env python2
"""Simple tests for Cloud Chaser debugging and validation.
"""
from __future__ import print_function
from ccio import CloudChaser, Stats, cleanup
import sys
import os
import argparse
import traceback
import random

def command_recv(args, cc):
    while not cc.join(1):
        pass


def command_send(args, cc):
    while 1:
        data = 'a' * 115  # ''.join(chr(n % 256) for n in range(4))
        # data = ''.join([chr(random.randrange(0, 0xff+1)) for _ in range(random.randrange(4, 200))])
        cc.io.send(CloudChaser.NMAC_SEND_STRM, 0x0000, data)
        # time.sleep(0.010)
        # sys.exit()


def main(args):
    stats = None

    if args.stats and args.command is not 'reset':
        stats = Stats()
        stats.start()

    cleanup.install(lambda: os._exit(0))

    cc = CloudChaser(stats=stats)
    cc.open(args.device)
    cc.io.status()

    if args.command == 'status':
        sys.exit(0)

    if args.verbose:
        cc.handler = print_packet

    if args.command == 'recv':
        command_recv(args, cc)
        sys.exit(0)

    if args.command == 'send':
        command_send(args, cc)
        sys.exit(0)

    if args.command == 'rainbow':
        cc.io.rainbow()
        sys.exit(0)


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
