#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
"""Time synchronization example.

On the same machine, you should see timestamps within
about half a millisecond of each other.
"""
import sys
import os
import time
import argparse
import argcomplete
from ccio.ccrf import CCRF


def run(args):
    ccrf = CCRF(args.device)

    ccrf.print_status()

    if args.receiver:
        for mesg in ccrf.recv(port=101):
            if mesg.type == 1:
                now = time.time()
                print(f"{now:.6f}")
            elif mesg.type == 0:
                ccrf.send(mesg.addr, mesg.port, mesg.type, wait=False)

    else:
        all_latency = []

        for _ in range(3):
            latency = time.time()
            ccrf.send(CCRF.ADDR_BCST, port=101, typ=0, wait=False)
            resp = next(ccrf.recv(port=101, typ=0, once=True))
            latency = time.time() - latency
            all_latency.append(latency)
            print(f"latency: {latency:.6f}")

        latency = sum(all_latency) / len(all_latency)
        print(f"average: {latency:.6f}")
        latency *= 0.65

        while 1:
            ccrf.send(CCRF.ADDR_BCST, port=101, typ=1, wait=False)
            time.sleep(latency)
            now = time.time()
            print(f"{now:.6f}")
            time.sleep(1.0)


def main():
    parser = argparse.ArgumentParser(prog="sync")
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
