"""Cloud Chaser RF Toolkit (CCRF).

Can be used both as a command line interface and a higher-level
alternative to the cloudchaser module.
"""
import sys
import os
import time
import argparse
import argcomplete
import threading

from . import util
from .util import adict
from .cloudchaser import CloudChaser


class CCRF:
    ADDR_BCST = CloudChaser.NET_ADDR_BCST

    device = None
    cc = None

    __addr = None

    __recv_queue = []
    __recv_sync = None
    __recv_wait = False
    __status_last = None

    def __init__(self, device):
        self.__recv_queue = []
        self.__recv_sync = threading.Semaphore(0)
        self.device = device
        self.cc = CloudChaser(handler=self.__handle_recv)
        self.cc.open(device)

    def close(self):
        """Close the serial connection to the device.
        """
        self.cc.close()

    def __load_status(self):
        self.__status_last = self.cc.io.status()
        self.__addr = self.__status_last.addr

    def status(self):
        """Returns the current device status as a dictionary/object.
        """
        self.__load_status()
        return self.__status_last

    def format_status(self, status=None):
        """Format a status object into a descriptive string.

        :param status: status object or none to get the current status.
        """
        return CloudChaser.format_status(self.status() if not status else status)

    def print_status(self, status=None, file=sys.stderr):
        """Shortcut to [retrieve and] print current status.
        """
        print(self.format_status(status), file=file)

    def addr(self):
        """Get the device network address.
        """
        if not self.__addr:
            self.__load_status()
        return self.__addr

    def rainbow(self):
        """Flashes the onboard RGB LEDs in a rainbow pattern.
        """
        self.cc.io.rainbow()

    def send(self, addr, port, typ, data=b''):
        """Send a simple datagram message.

        :param addr: Destination node address.
        :param port: Destination port number.
        :param typ: User type identifier.
        :param data: Data to send.
        """
        return self.cc.io.send(addr, port, typ, data)

    def mesg(self, addr, port, typ, data=b''):
        """Send a message and await ACK.

        :param addr: Destination node address.
        :param port: Destination port number.
        :param typ: User type identifier.
        :param data: Data to send.
        """
        return self.cc.io.mesg(addr, port, typ, data)

    def recv(self, port=None, typ=None, once=False):
        """Receive messages (iterator).

        :param port: filter by port.
        :param typ: filter by type.
        :param once: finish receiving after one message.
        :return: iterator that receives once or forever.
        """
        self.__recv_wait = True

        try:
            while 1:
                self.__recv_sync.acquire()
                mesg = self.__recv_queue.pop(0)

                if port is not None and mesg.port != port:
                    continue

                if typ is not None and mesg.type != typ:
                    continue

                yield mesg

                if once:
                    break

        finally:
            self.__recv_wait = False

    def trxn(self, addr, port, typ, wait, data=b''):
        """Transact data with a peer.

        Sends an ACKed message with request data and ACKs a received
        message with the response data.

        :param addr: address to transact with, can be broadcast.
        :param port: destination port.
        :param typ: destination type id.
        :param wait: wait time in ms, must be nonzero and < (2^32)-1
        :param data: transaction request data.
        :return: list of transaction responses (addr, data).
        """
        return self.cc.io.trxn(addr, port, typ, wait, data)

    def resp(self, addr, port, typ, data=b''):
        """Respond to a transaction (ACKed message).

        :param addr: Destination node address.
        :param port: Destination port number.
        :param typ: User type identifier.
        :param data: Data to send.
        """
        return self.cc.io.resp(addr, port, typ, data)

    def __handle_recv(self, cc, addr, dest, port, typ, data):
        if self.__recv_wait:
            self.__recv_queue.append(adict(
                addr=addr, dest=dest, port=port, type=typ, data=data
            ))
            self.__recv_sync.release()

    @staticmethod
    def argparse_device_arg(parser):
        return parser.add_argument(
            '-d', '--device', metavar='DEV', help='serial device or acm tty number',
            type=lambda p: p if p.startswith('/') else f"/dev/ttyACM{int(p)}",
            **util.arg_env_or_req('CCRF_DEV')
        )

    @staticmethod
    def main():
        parser = argparse.ArgumentParser(prog="ccrf")
        CCRF.argparse_device_arg(parser)
        parser.add_argument('-v', '--verbose', action='store_true', help='verbose output')
        subparsers = parser.add_subparsers(dest='command', title='commands', help='action to invoke', metavar='CMD')

        parser_status = subparsers.add_parser('status', aliases=['stat'], help='display status')
        CCRF._command_stat = CCRF._command_status

        parser_rainbow = subparsers.add_parser('rainbow', aliases=['rbow'], help='display rainbow')
        CCRF._command_rbow = CCRF._command_rainbow

        parser_send = subparsers.add_parser('send', help='send a datagram')
        parser_send.add_argument(
            '-d', '--dest',
            type=lambda p: int(p, 16),
            default=0,
            help='destination address (default: broadcast)'
        )
        parser_send.add_argument(
            '-p', '--path',
            type=lambda p: [int(pi, 16) for pi in p.split(',', 1)],
            default=(0, 0),
            help='destination route (port, type) (hex, default=0,0)'
        )
        parser_send.add_argument(
            '-m', '--mesg',
            action="store_true",
            help='send as a message and await receipt'
        )
        parser_send.add_argument(
            '-S', '--split',
            type=int,
            default=-1,
            help='send every n bytes (default: until eof)'
        )
        parser_send.add_argument(
            '-i', '--input',
            help='file to send data from (default: stdout or cmdline)'
        )
        parser_send.add_argument(
            'data',
            type=lambda p: bytearray(p, 'ascii'),
            default=b'-',
            nargs='?',
            help='data to send or "-"/nothing for stdin'
        )

        parser_recv = subparsers.add_parser('recv', help='receive data')
        parser_recv.add_argument(
            '-s', '--source',
            type=lambda p: int(p, 16),
            default=0,
            help='source address to receive from (hex, default=any)'
        )
        parser_recv.add_argument(
            '-p', '--path',
            type=lambda p: [int(pi, 16) for pi in p.split(',', 1)],
            default=(0, 0),
            help='source route (port, type) (hex, default=0,0)'
        )
        parser_recv.add_argument(
            '-b', '--bcast',
            action="store_true",
            help='include broadcast messages only'
        )
        parser_recv.add_argument(
            '-B', '--no-bcast',
            action="store_true",
            help='do not include broadcast messages'
        )
        parser_recv.add_argument(
            '-1', '--once',
            action="store_true",
            help='exit after receiving one message'
        )
        parser_recv.add_argument(
            '-n', '--newline',
            action="store_true",
            help='newline at end of stdout'
        )
        parser_recv.add_argument(
            '-N', '--mesg-newline',
            action="store_true",
            help='newline after each message on stdout'
        )
        parser_recv.add_argument(
            '-r', '--respond',
            action="store_true",
            help='respond to messages with data from stdin'
        )
        parser_recv.add_argument(
            '-o', '--out',
            help='file to receive into (default=stdout)'
        )
        parser_recv.add_argument(
            '-a', '--append',
            action="store_true",
            default=False,
            help='append to output file'
        )
        parser_recv.add_argument(
            '-f', '--flush',
            action="store_true",
            default=False,
            help='flush output on each receive'
        )

        parser_rxtx = subparsers.add_parser('rxtx', help='send and receive data')
        parser_rxtx.add_argument(
            '-s', '--source',
            type=lambda p: int(p, 16),
            default=0,
            help='source address to receive from (hex, default=any)'
        )
        parser_rxtx.add_argument(
            '-d', '--dest',
            type=lambda p: int(p, 16),
            default=None,
            help='destination address (default: source)'
        )
        parser_rxtx.add_argument(
            '-p', '--path',
            type=lambda p: [int(pi, 16) for pi in p.split(',', 1)],
            default=(0, 0),
            help='source route (port, type) (hex, default=0,0)'
        )
        parser_rxtx.add_argument(
            '-P', '--path-dest',
            type=lambda p: [int(pi, 16) for pi in p.split(',', 1)],
            default=None,
            help='destination route (port, type) (hex, default=path)'
        )
        parser_rxtx.add_argument(
            '-m', '--mesg',
            action="store_true",
            help='send as a message and await receipt'
        )
        parser_rxtx.add_argument(
            '-b', '--bcast',
            action="store_true",
            help='include broadcast messages only'
        )
        parser_rxtx.add_argument(
            '-B', '--no-bcast',
            action="store_true",
            help='do not include broadcast messages'
        )
        parser_rxtx.add_argument(
            '-1', '--once',
            action="store_true",
            help='exit after receiving one message'
        )
        parser_rxtx.add_argument(
            '-n', '--newline',
            action="store_true",
            help='newline at end of stdout'
        )
        parser_rxtx.add_argument(
            '-N', '--mesg-newline',
            action="store_true",
            help='newline after each message on stdout'
        )
        parser_rxtx.add_argument(
            '-S', '--split',
            type=int,
            default=-1,
            help='send every n bytes (default: until eof)'
        )
        parser_rxtx.add_argument(
            '-i', '--input',
            help='file to send data from (default: stdout or cmdline)'
        )
        parser_rxtx.add_argument(
            '-o', '--out',
            help='file to receive into (default=stdout)'
        )
        parser_rxtx.add_argument(
            '-a', '--append',
            action="store_true",
            help='append to output file'
        )
        parser_rxtx.add_argument(
            '-f', '--flush',
            action="store_true",
            help='flush output on each receive'
        )

        parser_monitor = subparsers.add_parser('monitor', help='monitor i/o stats')

        argcomplete.autocomplete(parser)
        args = parser.parse_args()

        ccrf = CCRF(args.device)

        try:
            eval(f"CCRF._command_{args.command}(ccrf, args)")
        except KeyboardInterrupt:
            sys.stderr.write(os.linesep)
        finally:
            time.sleep(0.00001)
            ccrf.close()

    @staticmethod
    def _command_status(ccrf, args):
        stat = ccrf.status()
        print(ccrf.format_status(stat), file=sys.stderr)

        if args.verbose:
            print("mac: rx={}/{}/{} tx={}/{}/{}".format(
                stat.mac_stat.recv.count, stat.mac_stat.recv.size, stat.mac_stat.recv.error,
                stat.mac_stat.send.count, stat.mac_stat.send.size, stat.mac_stat.send.error
            ), file=sys.stderr)

            print("phy: rx={}/{}/{} tx={}/{}/{}".format(
                stat.phy_stat.recv.count, stat.phy_stat.recv.size, stat.phy_stat.recv.error,
                stat.phy_stat.send.count, stat.phy_stat.send.size, stat.phy_stat.send.error
            ), file=sys.stderr)

    @staticmethod
    def _command_rainbow(ccrf, args):
        ccrf.rainbow()
        time.sleep(0.1)

    @staticmethod
    def __print_mesg(addr, dest, port, typ, data):
        print(
            f"{addr:04X}->{dest:04X} {port:02X}:{typ:02X} #{len(data)}",
            file=sys.stderr
        )

    @staticmethod
    def _command_send(ccrf, args, *, rxtx=False):
        if args.mesg and not args.dest:
            print("error: mesg requires destination", file=sys.stderr)
            exit(-1)

        send = (lambda *p: (0 if ccrf.send(*p) else 0)) if not args.mesg else ccrf.mesg
        result = 0

        path = args.path_dest if rxtx else args.path

        if not rxtx and args.data and args.data != b'-':
            result += send(args.dest, path[0], path[1], args.data)

        if args.input or rxtx or (not args.data or args.data == b'-'):
            inf = sys.stdin

            if args.input:
                inf = open(args.input, 'rb')

            try:
                while inf.readable():
                    if inf is sys.stdin:
                        data = bytes(inf.read(args.split), 'ascii')
                    else:
                        data = inf.read(args.split)

                    if data:
                        sent = send(args.dest, path[0], path[1], data)

                        if args.verbose:
                            CCRF.__print_mesg(ccrf.addr(), args.dest, path[0], path[1], data)

                        result += sent
                    else:
                        break

            except IOError:
                pass
            finally:
                exit(result)

        exit(result)

    @staticmethod
    def _command_recv(ccrf, args):
        out = sys.stdout

        if args.out:
            out = open(args.out, 'w+b' if args.append else 'wb')

        try:
            for mesg in ccrf.recv(port=args.path[0], typ=args.path[1]):
                if mesg.dest == CloudChaser.NET_ADDR_BCST:
                    if args.no_bcast:
                        continue
                elif args.bcast or mesg.dest != ccrf.addr():
                    continue

                if args.source and mesg.addr != args.source:
                    continue

                if out is sys.stdout:
                    out.write(
                        str(mesg.data, 'ascii') +
                        (os.linesep if args.mesg_newline else '')
                    )
                else:
                    out.write(mesg.data)

                if args.flush:
                    out.flush()

                if args.verbose:
                    CCRF.__print_mesg(mesg.addr, mesg.dest, mesg.port, mesg.type, mesg.data)

                if args.respond:
                    if not args.flush:
                        out.flush()

                    data = bytes(sys.stdin.read(), 'ascii')

                    if data:
                        ccrf.mesg(mesg.addr, mesg.port, mesg.type, data)

                if args.once:
                    break
        finally:
            if out is sys.stdout and args.newline:
                out.write(os.linesep)

                if args.flush:
                    out.flush()

            out.close()

    @staticmethod
    def _command_rxtx(ccrf, args):
        if args.dest is None:
            args.dest = args.source

        if args.path_dest is None:
            args.path_dest = args.path

        threading.Thread(
            target=lambda: CCRF._command_send(ccrf, args, rxtx=True),
            daemon=True
        ).start()

        args.respond = False
        CCRF._command_recv(ccrf, args)


if __name__ == '__main__':
    CCRF.main()
