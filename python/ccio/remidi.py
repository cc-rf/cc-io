#!/usr/bin/env python2
"""Simple tests for Cloud Chaser debugging and validation.
"""
from __future__ import print_function
from ccio import CloudChaser, cleanup
import sys
import os
import argparse
import traceback
import struct
import mido
from mido.messages.encode import encode_message

def main(args):
    midi_device = None

    for inp in mido.get_input_names():
        if args.midi.lower() in inp.lower():
            print("found device:", inp, file=sys.stderr)
            midi_device = inp
            break

    if not midi_device:
        print("no matching device found", file=sys.stderr)
        sys.exit(1)

    cc = CloudChaser()
    cc.open(args.device)
    cc.io.status()

    with mido.open_input(midi_device) as inport:
        for msg in inport:
            # encoded = "".join(chr(c) for c in encode_message(msg.dict()))
            # packet = struct.pack("B{}s".format(len(encoded)), (1 << 4) | msg.channel, encoded)

            # byts = msg.bytes()
            # header = ((byts[0] >> 4) & 0xFF) | (1 << 4)
            packet = "".join(chr(c) for c in msg.bytes())

            # if len(packet) < 4:
            #     packet += '\x00' * (4 - len(packet))

            if args.verbose:
                raw = " ".join("{:02X}".format(ord(c)) for c in packet)
                print(str(msg).ljust(59), raw)

            cc.io.send_wait(CloudChaser.NMAC_SEND_STRM, 0x0000, packet)

    # if args.verbose:
    #     cc.handler = print_packet

    # while not cc.join(1):
    #     pass


def print_packet(cc, node, peer, dest, rssi, lqi, data):
    print("<{:04X}> {:04X}->{:04X}: ({}) {}".format(
        node, peer, dest, len(data), " ".join("{:02X}".format(ord(ch)) for ch in data)
    ))

    # print("{:04X}->{:04X}: ({})".format(peer, dest, len(data)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--device', required=True, metavar="DEVICE", help='cloud chaser serial port')
    parser.add_argument('-m', '--midi', required=True, metavar="NAME", help='midi device to search for')
    parser.add_argument('-v', '--verbose', action='store_true', help='verbose output')
    # parser.add_argument('-D', '--debug', action='store_true', help='debug mode')
    # parser.add_argument('command', help='program command')
    # parser.add_argument('param', nargs="*", help='command params')

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

