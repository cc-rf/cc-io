#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
"""Packet throughput benchmarking.
"""
import sys
import os
import time
import random
import argparse
import argcomplete
from ccio.ccrf import CCRF


def run(ccrf, args):
    ccrf.print_status()

    if not args.addr:
        if args.trxn:
            for mesg in ccrf.recv(port=101, typ=1):
                ccrf.resp(mesg.addr, mesg.port, mesg.type, mesg.data)
        else:
            for mesg in ccrf.recv():
                pass

    else:
        data = b'a' * CCRF.MTU * (round(CCRF.MTU * .8) * 3)

        if args.trxn:
            while 1:
                list(ccrf.trxn(args.addr, port=101, typ=1, wait=1000, data=data))

        else:
            while 1:
                # data = bytes(random.randint(0, 255) for _ in range(random.randint(0, CCRF.MTU)))
                ccrf.send(args.addr, port=101, typ=2, data=data, mesg=True, wait=False)


def main():
    parser = argparse.ArgumentParser(prog="bench")
    CCRF.argparse_device_arg(parser)
    parser.add_argument('addr', nargs='?', default=0, type=lambda p: int(p, 16), help='address to talk to or none to recv')
    parser.add_argument('-t', '--trxn', action="store_true", help='transaction')
    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    try:
        with CCRF(args.device, stats=sys.stderr) as ccrf:
            run(ccrf, args)

    except KeyboardInterrupt:
        exit("")


if __name__ == '__main__':
    main()
