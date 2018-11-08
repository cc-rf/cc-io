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
import subprocess
import traceback

from . import util
from .util import adict
from .cloudchaser import CloudChaser
from .stats import Stats
from .asyncq import AsyncQ


class CCRF:
    ADDR_BCST = CloudChaser.NET_ADDR_BCST

    MAC_FLAG_MASK = CloudChaser.NMAC_FLAG_MASK

    MAC_DGRM = CloudChaser.NMAC_SEND_DGRM
    MAC_MESG = CloudChaser.NMAC_SEND_MESG
    MAC_STRM = CloudChaser.NMAC_SEND_STRM

    MTU = CloudChaser.NET_BASE_SIZE

    EVNT_PEER = CloudChaser.NET_EVNT_PEER
    EVNT_PEER_SET = CloudChaser.NET_EVNT_PEER_SET
    EVNT_PEER_EXP = CloudChaser.NET_EVNT_PEER_EXP
    EVNT_PEER_OUT = CloudChaser.NET_EVNT_PEER_OUT
    EVNT_PEER_UPD = CloudChaser.NET_EVNT_PEER_UPD

    device = None
    cc = None
    stats = None

    __addr = None

    __recv_q = None
    __recv_mac_q = None
    __evnt_q = None

    __status_last = None

    def __init__(self, device, stats=None):
        self.__recv_q = AsyncQ()
        self.__recv_mac_q = AsyncQ()
        self.__evnt_q = AsyncQ()

        self.device = device

        if stats:
            self.stats = Stats(stats)
            self.stats.start()

        self.cc = CloudChaser(
            stats=self.stats,
            handler=self.__handle_recv,
            mac_handler=self.__handle_recv_mac,
            evnt_handler=self.__handle_evnt
        )

        self.cc.open(device)

    def close(self):
        """Close the serial connection to the device.
        """
        self.cc.close()

    def __load_status(self):
        self.__status_last = self.cc.io.status()
        self.__addr = self.__status_last.addr

    def __clear_status(self):
        self.__status_last = None
        self.__addr = None

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

    def addr_set(self, orig, addr):
        """Set the device address.
        :param orig: Current device address.
        :param addr: Desired new address.
        :return: Actual new address or 0 for error.
        """
        rslt = self.cc.io.config_addr(orig, addr)
        self.__clear_status()
        return rslt

    def echo(self, data):
        """Echo data from the device.

        :param data: Data to echo.
        """
        if isinstance(data, str):
            data = bytes(data, 'ascii')

        return self.cc.io.echo(data)

    def rainbow(self):
        """Flashes the onboard RGB LEDs in a rainbow pattern.
        """
        self.cc.io.rainbow()

    def send(self, addr, port, typ, data=b'', mesg=False):
        """Send a simple datagram message.

        :param addr: Destination node address.
        :param port: Destination port number.
        :param typ: User type identifier.
        :param data: Data to send.
        :param mesg: Request ACK (but do not wait for result).
        """
        return self.cc.io.send(addr, port, typ, data, mesg=mesg)

    def send_mac(self, typ, dest, data, addr=0, wait=True):
        """Send a MAC-layer datagram.

        :param typ: MAC message type: CCRF.MAC_DGRM, CCRF.MAC_MESG, or CCRF.MAC_STRM.
        :param dest: Destination node address.
        :param data: Data to send.
        :param addr: Source address (0 for default).
        :param wait: Wait until TX complete to return.
        """
        if wait:
            return self.cc.io.mac_send_wait(typ, dest, data, addr)

        return self.cc.io.mac_send(typ, dest, data, addr)

    def mesg(self, addr, port, typ, data=b''):
        """Send a message and await ACK.

        :param addr: Destination node address.
        :param port: Destination port number.
        :param typ: User type identifier.
        :param data: Data to send.
        :return: Number of packets ACKed.
        """
        return self.cc.io.mesg(addr, port, typ, data)

    def evnt(self, once=False, timeout=None):
        """Receive events.
        :param once: finish receiving after one message.
        :param timeout: timeout in seconds or None.
        :return: Iterater of adict(event,data).
        """
        return self.__evnt_q.recv(once, timeout)

    def recv(self, port=None, typ=None, once=False, timeout=None):
        """Receive messages (iterator).

        :param port: filter by port.
        :param typ: filter by type.
        :param once: finish receiving after one message.
        :param timeout: timeout in seconds or None.
        :return: iterator that receives once or forever.
        """
        for mesg in self.__recv_q.recv(once=False, timeout=timeout):

            if port is not None and mesg.port != port:
                continue

            if typ is not None and mesg.type != typ:
                continue

            yield mesg

            if once:
                break

    def recv_mac(self, once=False, timeout=None):
        """Receive MAC messages (iterator).

        :param once: finish receiving after one message.
        :param timeout: timeout in seconds or None.
        :return: iterator that receives once or forever.
        """
        return self.__recv_mac_q.recv(once, timeout)

    def trxn(self, addr, port, typ, wait, data=b''):
        """Transact data with a peer.

        Sends an ACKed message with request data and ACKs a received
        message with the response data.

        :param addr: address to transact with, can be broadcast.
        :param port: destination port.
        :param typ: destination type id.
        :param wait: wait time in ms, must be nonzero and < 2^32.
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

    def peers(self):
        """Get the peer table from the device.

        Includes all advertised known peer associations.

        :return: adict{node, time, peers=adict{node, peer, last, rssi, lqi}}.
        """
        return self.cc.io.peer()

    def __handle_recv(self, addr, dest, port, typ, data):
        self.__recv_q.send(adict(
            addr=addr, dest=dest, port=port, type=typ, data=data
        ))

    def __handle_recv_mac(self, addr, peer, dest, rssi, lqi, data):
        self.__recv_mac_q.send(adict(
            addr=addr, peer=peer, dest=dest, rssi=rssi, lqi=lqi, data=data
        ))

    def __handle_evnt(self, evnt):
        self.__evnt_q.send(evnt)

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
        subparsers = parser.add_subparsers(dest='command', title='commands', help='action to invoke', metavar='CMD')

        parser_status = subparsers.add_parser('status', aliases=['stat'], help='display status')
        parser_status.add_argument('-v', '--verbose', action='store_true', help='verbose output')
        CCRF._command_stat = CCRF._command_status

        parser_echo = subparsers.add_parser('echo', help='make the device echo back')
        parser_echo.add_argument(
            'data',
            type=str,
            default='-',
            nargs='?',
            help='data to echo or "-"/nothing for stdin'
        )

        parser_rainbow = subparsers.add_parser('rainbow', aliases=['rbow'], help='display rainbow')
        CCRF._command_rbow = CCRF._command_rainbow

        parser_peer = subparsers.add_parser('peer', help='print peer table')

        def valid_split(s):
            s = int(s)

            if not (-1 <= s < 0x10000):
                raise argparse.ArgumentTypeError("split must be in [-1, 16K)")

            return s

        parser_send = subparsers.add_parser('send', help='send a datagram')
        parser_send.add_argument('-v', '--verbose', action='store_true', help='verbose output')
        parser_send.add_argument(
            '-d', '--dest',
            type=lambda p: int(p, 16),
            default=0,
            help='destination address (default: broadcast).'
        )
        parser_send.add_argument(
            '-p', '--path',
            type=lambda p: [int(pi) for pi in p.split(',', 1)],
            default=(0, 0),
            help='source route (port: 0-1023, type: 0-15) (int, default=0,0).'
        )
        parser_send.add_argument(
            '-m', '--mesg',
            action="store_true",
            help='send as a message and await receipt.'
        )
        parser_send.add_argument(
            '-S', '--split',
            type=valid_split,
            default=-1,
            help='send every n bytes (default: until eof).'
        )
        parser_send.add_argument(
            '-i', '--input',
            default=sys.stdin,
            help='file to send data from (default: stdin).'
        )
        parser_send.add_argument(
            '-I', '--no-input',
            action="store_true",
            help='do not read from stdin by default.'
        )
        parser_send.add_argument(
            '-tx', '--data',
            type=lambda p: bytes(p, 'ascii'),
            action='append',
            default=[],
            help='data to send (before input if given, otherwise -I implied).'
        )

        parser_recv = subparsers.add_parser('recv', help='receive data')
        parser_recv.add_argument('-v', '--verbose', action='store_true', help='verbose output')
        parser_recv.add_argument(
            '-s', '--source',
            type=lambda p: int(p, 16),
            default=0,
            help='source address to receive from (hex, default=any).'
        )
        parser_recv.add_argument(
            '-p', '--path',
            type=lambda p: [int(pi) for pi in p.split(',', 1)],
            default=(0, 0),
            help='source route (port: 0-1023, type: 0-15) (int, default=0,0).'
        )
        parser_recv.add_argument(
            '-b', '--bcast',
            action="store_true",
            help='include broadcast messages only.'
        )
        parser_recv.add_argument(
            '-B', '--no-bcast',
            action="store_true",
            help='do not include broadcast messages.'
        )
        parser_recv.add_argument(
            '-1', '--once',
            action="store_true",
            help='exit after receiving one message (unless -T).'
        )
        parser_recv.add_argument(
            '-t', '--timeout',
            type=float,
            default=None,
            help='amount of time in seconds to receive.'
        )
        parser_recv.add_argument(
            '-T', '--timeout-after-first',
            action="store_true",
            help='start timeout clock after first receive.'
        )
        parser_recv.add_argument(
            '-n', '--newline',
            action="store_true",
            help='newline at end of stdout.'
        )
        parser_recv.add_argument(
            '-N', '--mesg-newline',
            action="store_true",
            help='newline after each message on stdout.'
        )
        parser_recv.add_argument(
            '-r', '--respond',
            action="store_true",
            help='respond to messages with data from stdin.'
        )
        parser_recv.add_argument(
            '-o', '--out',
            default=sys.stdout,
            help='file to receive into (default=stdout).'
        )
        parser_recv.add_argument(
            '-a', '--append',
            action="store_true",
            default=False,
            help='append to output file.'
        )
        parser_recv.add_argument(
            '-f', '--flush',
            action="store_true",
            default=False,
            help='flush output on each receive.'
        )

        parser_rxtx = subparsers.add_parser('rxtx', help='send and receive data')
        parser_rxtx.add_argument('-v', '--verbose', action='store_true', help='verbose output')
        parser_rxtx.add_argument(
            '-s', '--source',
            type=lambda p: int(p, 16),
            default=0,
            help='source address to receive from (hex, default=any).'
        )
        parser_rxtx.add_argument(
            '-d', '--dest',
            type=lambda p: int(p, 16),
            default=None,
            help='destination address (default: source).'
        )
        parser_rxtx.add_argument(
            '-p', '--path',
            type=lambda p: [int(pi) for pi in p.split(',', 1)],
            default=(0, 0),
            help='source route (port: 0-1023, type: 0-15) (int, default=0,0).'
        )
        parser_rxtx.add_argument(
            '-P', '--path-dest',
            type=lambda p: [int(pi) for pi in p.split(',', 1)],
            default=None,
            help='destination route (port: 0-1023, type: 0-15) (int, default=path).'
        )
        parser_rxtx.add_argument(
            '-m', '--mesg',
            action="store_true",
            help='send as a message and await receipt.'
        )
        parser_rxtx.add_argument(
            '-b', '--bcast',
            action="store_true",
            help='include broadcast messages only.'
        )
        parser_rxtx.add_argument(
            '-B', '--no-bcast',
            action="store_true",
            help='do not include broadcast messages.'
        )
        parser_rxtx.add_argument(
            '-1', '--once',
            action="store_true",
            help='exit after receiving one message (unless -T).'
        )
        parser_rxtx.add_argument(
            '-t', '--timeout',
            type=float,
            default=None,
            help='amount of time in seconds to receive.'
        )
        parser_rxtx.add_argument(
            '-T', '--timeout-after-first',
            action="store_true",
            help='start timeout clock after first receive.'
        )
        parser_rxtx.add_argument(
            '-n', '--newline',
            action="store_true",
            help='newline at end of stdout.'
        )
        parser_rxtx.add_argument(
            '-N', '--mesg-newline',
            action="store_true",
            help='newline after each message on stdout.'
        )
        parser_rxtx.add_argument(
            '-S', '--split',
            type=valid_split,
            default=-1,
            help='send every n bytes (default: until eof).'
        )
        parser_rxtx.add_argument(
            '-i', '--input',
            default=sys.stdin,
            help='file to send data from (default: stdin).'
        )
        parser_rxtx.add_argument(
            '-I', '--no-input',
            action="store_true",
            help='do not read from stdin by default.'
        )
        parser_rxtx.add_argument(
            '-o', '--out',
            default=sys.stdout,
            help='file to receive into (default=stdout).'
        )
        parser_rxtx.add_argument(
            '-a', '--append',
            action="store_true",
            help='append to output file.'
        )
        parser_rxtx.add_argument(
            '-f', '--flush',
            action="store_true",
            help='flush output on each receive.'
        )
        parser_rxtx.add_argument(
            '-tx', '--data',
            type=lambda p: bytes(p, 'ascii'),
            action='append',
            default=[],
            help='data to send (before input if given, otherwise -I implied).'
        )
        parser_rxtx.add_argument(
            '-e', '--exec',
            type=lambda p: [pi.strip() for pi in p.split()],
            help='execute program and pipe stdin/stdout over rf.'
        )
        parser_rxtx.add_argument(
            '-ei', '--exec-in',
            type=lambda p: [pi.strip() for pi in p.split()],
            help='execute program and pipe stdout over rf.'
        )
        parser_rxtx.add_argument(
            '-eo', '--exec-out',
            type=lambda p: [pi.strip() for pi in p.split()],
            help='execute program and pipe to stdin from rf.'
        )

        parser_addr = subparsers.add_parser('addr', help='show [and set] device address.')
        parser_addr.add_argument('-q', '--quiet', action='store_true', help='do not print anything.')
        parser_addr.add_argument(
            'orig',
            nargs='?',
            type=lambda p: int(p, 16),
            default=None,
            help='current device address.'
        )
        parser_addr.add_argument(
            'addr',
            nargs='?',
            type=lambda p: int(p, 16),
            default=None,
            help='new device address.'
        )

        parser_monitor = subparsers.add_parser('monitor', help='monitor i/o stats')

        argcomplete.autocomplete(parser)
        args = parser.parse_args()

        ccrf = CCRF(args.device)

        try:
            command = getattr(CCRF, f"_command_{args.command}")
            command(ccrf, args)
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
            print("mac: rx={}/{}/{} tx={}/{}/{} stack: {}".format(
                stat.mac_stat.recv.count, stat.mac_stat.recv.size, stat.mac_stat.recv.error,
                stat.mac_stat.send.count, stat.mac_stat.send.size, stat.mac_stat.send.error,
                stat.mac_su_rx
            ), file=sys.stderr)

            print("phy: rx={}/{}/{} tx={}/{}/{} stack: {}".format(
                stat.phy_stat.recv.count, stat.phy_stat.recv.size, stat.phy_stat.recv.error,
                stat.phy_stat.send.count, stat.phy_stat.send.size, stat.phy_stat.send.error,
                stat.phy_su
            ), file=sys.stderr)

            print("heap: free={} usage={}".format(stat.heap_free, stat.heap_usage), file=sys.stderr)

    @staticmethod
    def _command_echo(ccrf, args):

        if args.data == '-':
            while sys.stdin.readable():
                ccrf.echo(sys.stdin.read())

        else:
            ccrf.echo(args.data)

        time.sleep(0.001)

    @staticmethod
    def _command_rainbow(ccrf, args):
        ccrf.rainbow()
        time.sleep(0.1)

    @staticmethod
    def _command_addr(ccrf, args):
        addr = ccrf.addr()

        if args.orig is not None:
            if args.addr is None:
                raise argparse.ArgumentError("addr is required.")

            addr = ccrf.addr_set(args.orig, args.addr)

        if not args.quiet:
            print(f"0x{addr if addr else ccrf.addr():04X}")

        exit(addr != ccrf.addr())

    @staticmethod
    def _command_peer(ccrf, args):
        peer_info = ccrf.peers()

        print(f"{peer_info.node:04X}: t={peer_info.time}", file=sys.stderr)

        for peer in peer_info.peers:
            print(
                f"  {peer.node:04X}/{peer.peer:04X}: t={peer.last} q={peer.lqi} r={peer.rssi}",
                file=sys.stderr
            )

    @staticmethod
    def __print_mesg(addr, dest, port, typ, data):
        print(
            f"{addr:04X}->{dest:04X} {port:03X}:{typ:01X} #{len(data)}",
            file=sys.stderr
        )

    @staticmethod
    def _command_monitor(ccrf, args):
        for evnt in ccrf.evnt():
            if evnt.id == CCRF.EVNT_PEER:
                action = {0: 'SET', 1: 'EXP', 2: 'OUT', 3: 'UPD'}.get(evnt.action, evnt.action)

                print(f"{evnt.addr:04X}: {action}")
            else:
                print(f"event: {evnt.id} data={evnt.data}")

            CCRF._command_peer(ccrf, args)

    @staticmethod
    def _command_send(ccrf, args, *, rxtx=False):
        if rxtx:
            def done(r): return r
        else:
            done = exit

        if args.mesg and not args.dest:
            return done("error: mesg requires destination")

        if args.no_input:
            args.input = None
        elif args.input != sys.stdin:
            size = os.path.getsize(args.input)

            if size > 16384 and args.split < 0:
                print(f"{args.input}: splitting {size} bytes into 16K chunks", file=sys.stderr)
                args.split = 16384

        send = ccrf.send if not args.mesg else ccrf.mesg
        result = 0

        path = args.path_dest if rxtx else args.path

        for data in args.data:
            result += send(args.dest, path[0], path[1], data)

        if args.verbose and not args.input and not args.data:
            return done("warning: nothing sent")

        if args.input == sys.stdin and args.data:
            return done(result)

        inf = open(args.input, 'rb') if isinstance(args.input, str) else args.input

        read = inf.buffer.read if hasattr(inf, 'buffer') else inf.read

        try:
            while inf.readable():
                data = read(args.split)

                if data:
                    sent = send(args.dest, path[0], path[1], data)

                    if args.verbose:
                        CCRF.__print_mesg(ccrf.addr(), args.dest, path[0], path[1], data)

                    result += sent
                else:
                    break

        except IOError:
            pass

        return done(result)

    @staticmethod
    def _command_recv(ccrf, args):
        out = open(args.out, 'w+b' if args.append else 'wb') if isinstance(args.out, str) else args.out

        write = out.buffer.write if hasattr(out, 'buffer') else out.write

        try:
            last = 0

            while 1:
                for mesg in ccrf.recv(port=args.path[0], typ=args.path[1], timeout=args.timeout):
                    last = time.time()

                    if mesg.dest == CloudChaser.NET_ADDR_BCST:
                        if args.no_bcast:
                            continue
                    elif args.bcast or mesg.dest != ccrf.addr():
                        continue

                    if args.source and mesg.addr != args.source:
                        continue

                    write(mesg.data)

                    if args.flush:
                        out.flush()

                    if args.verbose:
                        CCRF.__print_mesg(mesg.addr, mesg.dest, mesg.port, mesg.type, mesg.data)

                    if args.respond:
                        if not args.flush:
                            out.flush()

                        data = bytes(sys.stdin.read())

                        if data:
                            ccrf.mesg(mesg.addr, mesg.port, mesg.type, data)

                    if args.once or args.timeout_after_first:
                        break

                if not args.timeout:
                    break

                if args.timeout_after_first:
                    if not last:
                        continue

                    since = time.time() - last

                    if since >= args.timeout:
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

        if args.exec:
            if args.input != sys.stdin or args.out != sys.stdout:
                raise ValueError("cannot specify input or output files when using pipe")

            sp = subprocess.Popen(
                args=args.exec, executable=args.exec[0],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=sys.stderr
            )

            args.input = sp.stdout
            args.out = sp.stdin
        else:
            if args.input != sys.stdin:
                raise ValueError("cannot specify input files when using input pipe")

            if args.exec_in:
                spi = subprocess.Popen(
                    args=args.exec_in, executable=args.exec_in[0],
                    stdout=subprocess.PIPE, stderr=sys.stderr
                )

                args.input = spi.stdout

            if args.exec_out:
                spi = subprocess.Popen(
                    args=args.exec_out, executable=args.exec_out[0],
                    stdin=subprocess.PIPE, stdout=sys.stdout,
                    stderr=sys.stderr
                )

                args.out = spi.stdin

        def run_send():
            rslt = CCRF._command_send(ccrf, args, rxtx=True)

            if isinstance(rslt, str):
                print(rslt, file=sys.stderr)

        threading.Thread(
            target=run_send,
            daemon=True
        ).start()

        args.respond = False
        CCRF._command_recv(ccrf, args)


if __name__ == '__main__':
    CCRF.main()
