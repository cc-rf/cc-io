#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
"""Point-to-point IP-over-RF tunnel.
"""
import sys
import argparse
import argcomplete
from threading import Thread
from pytap2 import TapDevice, TapMode

from ccio.ccrf import CCRF

TUN_PORT = 42
TUN_TYPE = 3


def run(ccrf, tun, args):
    ccrf.print_status()

    def recv():
        addr = args.addr if args.addr != 0 else None
        ccrf_addr = ccrf.addr() if args.addr != 0 else 0

        for mesg in ccrf.recv(addr=addr, dest=ccrf_addr, port=TUN_PORT, typ=TUN_TYPE):
            tun.write(mesg.data)

    Thread(target=recv, daemon=True).start()

    while 1:
        data = tun.read()
        ccrf.mesg(args.addr, port=TUN_PORT, typ=TUN_TYPE, data=data, wait=False)


def main():
    parser = argparse.ArgumentParser(prog="tun")
    CCRF.argparse_device_arg(parser)
    parser.add_argument('net', help='tunnel network address')
    parser.add_argument('addr', type=lambda p: int(p, 16), help='tunnel endpoint address')
    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    try:
        with TapDevice(name="cctun", mode=TapMode.Tun) as tun:
            tun.ifconfig(address=args.net)

            with CCRF(args.device, stats=sys.stderr) as ccrf:
                run(ccrf, tun, args)

    except KeyboardInterrupt:
        exit("")


if __name__ == '__main__':
    main()
