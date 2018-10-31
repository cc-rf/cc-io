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
        # for mesg in ccrf.recv(port=102, typ=1):
        #     ccrf.resp(mesg.addr, mesg.port, mesg.type)

        for mesg in ccrf.recv_mac():
            pass

    else:
        data = b'a' * 1024

        # while 1:
        #     list(ccrf.trxn(0x4BD3, port=102, typ=1, wait=100, data=data))

        while 1:
            ccrf.mesg(0x4BC9, 0, 0, data)


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
