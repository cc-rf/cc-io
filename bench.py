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
                data = bytes(random.randint(0, 255) for _ in range(random.randint(0, CCRF.MTU*2)))
                ccrf.resp(mesg.addr, mesg.port, mesg.type, data)
        else:
            for mesg in ccrf.recv():
                pass

    else:
        # The max number of mac packets that can be sent in 40ms, with 1 MTU = 2.64ms, is technically 15.
        # However, measurement shows that 12 yields a receive rate of 25 (net) packets per second, or one
        #   per channel. This is accounted for by the ~600us of processing/rtt required per packet.

        data = b'a' * CCRF.MTU * 12

        if args.trxn:
            while 1:
                data = bytes(random.randint(0, 255) for _ in range(random.randint(0, CCRF.MTU*2)))
                list(ccrf.trxn(args.addr, port=101, typ=1, wait=1000, data=data))

        else:
            while 1:
                ccrf.send(args.addr, port=101, typ=2, data=data, mesg=False, wait=False)


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
