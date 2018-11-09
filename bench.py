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
        if args.trxn:
            for mesg in ccrf.recv(port=101, typ=1):
                ccrf.send(mesg.addr, mesg.port, mesg.type)
        else:
            for mesg in ccrf.recv():
                pass

    else:
        data = b'a' * (CCRF.MTU * 10)

        if args.trxn:
            while 1:
                list(ccrf.trxn(0x4BD3, port=101, typ=1, wait=1000, data=data))

        else:
            while 1:
                # ccrf.send_mac(CCRF.MAC_DGRM, 0x0000, data=data, wait=False)
                ccrf.send(0x4BD3, port=101, typ=2, data=data)


def main():
    parser = argparse.ArgumentParser(prog="bench")
    CCRF.argparse_device_arg(parser)
    parser.add_argument('-r', '--receiver', action="store_true", help='sync receiver')
    parser.add_argument('-t', '--trxn', action="store_true", help='transaction')
    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    try:
        run(args)
    except KeyboardInterrupt:
        exit("")


if __name__ == '__main__':
    main()
