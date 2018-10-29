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
    ccrf = CCRF(args.device, stats=True)

    ccrf.print_status()

    if args.receiver:
        for mesg in ccrf.recv(port=102):
            pass

    else:
        data = b'a' * 113

        while 1:
            ccrf.mesg(0x4bc9, port=102, typ=1, data=data)


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
