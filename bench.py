#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
"""Packet throughput benchmarking.
"""
import sys
import os
import time
import argparse
import argcomplete
from ccio.ccrf import CCRF


def run(args):
    ccrf = CCRF(args.device, stats=sys.stderr)

    ccrf.print_status()

    if args.receiver:
        for mesg in ccrf.recv(port=101, typ=1):
            pass

    else:
        data = b'a' * CCRF.BASE_SIZE

        while 1:
            # ccrf.send_mac(CCRF.MAC_DGRM, 0x4BC9, data=data, wait=False)
            ccrf.mesg(0x4BC9, port=101, typ=1, data=data)


def main():
    parser = argparse.ArgumentParser(prog="bench")
    CCRF.argparse_device_arg(parser)
    parser.add_argument('-r', '--receiver', action="store_true", help='sync receiver')
    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    try:
        run(args)
    except KeyboardInterrupt:
        exit("")


if __name__ == '__main__':
    main()
