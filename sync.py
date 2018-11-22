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
from pickle import loads, dumps
from ccio.ccrf import CCRF


def run(ccrf, args):
    ccrf.print_status()

    if not args.addr:
        latency = 0

        for mesg in ccrf.recv(port=101):
            if mesg.type == 2:
                latency = 0.745 * (loads(mesg.data) / 2)
                print(f"latency: {latency:.6f}")

            elif mesg.type == 1:

                time.sleep(latency)

                now = time.time()

                print(f"{now:.6f}")

    else:
        all_latency = []

        for _ in range(10):
            latency = time.time()

            if not ccrf.mesg(args.addr, port=101, typ=0):
                exit("tx fail.")

            latency = (time.time() - latency) / 2

            all_latency.append(latency)

            print(f"latency: {latency:.6f}")

        latency = sum(all_latency) / len(all_latency)

        print(f"average: {latency:.6f}")

        if not ccrf.mesg(args.addr, port=101, typ=2, data=dumps(latency)):
            exit("tx fail.")

        time.sleep(0.100)

        while 1:
            if not ccrf.mesg(args.addr, port=101, typ=1):
                exit("tx fail.")

            now = time.time()

            print(f"{now:.6f}")

            time.sleep(1.0)


def main():
    parser = argparse.ArgumentParser(prog="sync")
    CCRF.argparse_device_arg(parser)
    parser.add_argument('addr', nargs='?', default=0, type=lambda p: int(p, 16), help='address to sync with or none to wait')
    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    try:
        with CCRF(args.device) as ccrf:
            run(ccrf, args)
    except KeyboardInterrupt:
        exit("")


if __name__ == '__main__':
    main()
