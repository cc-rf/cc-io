#!/usr/bin/env python2
"""TCP tunneling via RF.
"""
from __future__ import print_function
from ccio import CloudChaser, cleanup
import sys
import os
import argparse
import traceback


def main(args):
    cc = CloudChaser()
    cc.open(args.device)
    cc.io.status()


def print_packet(cc, node, peer, dest, rssi, lqi, data):
    print("<{:04X}> {:04X}->{:04X}: ({}) {}".format(
        node, peer, dest, len(data), " ".join("{:02X}".format(ord(ch)) for ch in data)
    ))

    # print("{:04X}->{:04X}: ({})".format(peer, dest, len(data)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--device', metavar='DEV', required=True, help='serial input device')
    parser.add_argument('-v', '--verbose', action='store_true', help='verbose output')
    # parser.add_argument('command', help='program command')
    # parser.add_argument('param', nargs="*", help='command params')

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
