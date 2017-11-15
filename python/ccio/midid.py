#!/usr/bin/env python2
"""Simple tests for Cloud Chaser debugging and validation.
"""
from __future__ import print_function
from ccio import cleanup
import sys
import os
import argparse
import traceback
import mido


def main(args):
    if args.list:
        for inp in mido.get_input_names():
            if not args.midi or args.midi.lower() in inp.lower():
                print(inp)
        return

    if not args.midi:
        print("error: midi name required", file=sys.stderr);
        sys.exit(1)

    midi_device = None

    for inp in mido.get_input_names():
        if args.midi.lower() in inp.lower():
            print("found device:", inp, file=sys.stderr)
            midi_device = inp
            break

    if not midi_device:
        print("no matching device found", file=sys.stderr)
        sys.exit(1)

    with mido.open_input(midi_device) as inport:
        for msg in inport:
            raw = " ".join("{:02X}".format(c) for c in msg.bytes())
            print(str(msg).ljust(59), raw)


def print_packet(cc, node, peer, dest, rssi, lqi, data):
    print("<{:04X}> {:04X}->{:04X}: ({}) {}".format(
        node, peer, dest, len(data), " ".join("{:02X}".format(ord(ch)) for ch in data)
    ))

    # print("{:04X}->{:04X}: ({})".format(peer, dest, len(data)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-m', '--midi', metavar="NAME", help='midi device to search for')
    parser.add_argument('-l', '--list', action='store_true', help='list devices, optionally matching name')
    # parser.add_argument('-v', '--verbose', action='store_true', help='verbose output')

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

