"""Cloud Chaser RF Toolkit (CCRF).

Can be used both as a command line interface and a higher-level
alternative to the cloudchaser module.
"""
import sys
import os
import re
import time
import argparse
import argcomplete
import threading
import subprocess

from . import util
from .util import adict
from .cloudchaser import CloudChaser
from .stats import Stats
from .asyncq import AsyncQ


class CCRF:
    ADDR_BCST = CloudChaser.NET_ADDR_BCST
    ADDR_NONE = CloudChaser.NET_ADDR_INVL

    MAC_FLAG_MASK = CloudChaser.NMAC_FLAG_MASK

    MAC_DGRM = CloudChaser.NMAC_SEND_DGRM
    MAC_MESG = CloudChaser.NMAC_SEND_MESG
    MAC_STRM = CloudChaser.NMAC_SEND_STRM

    MTU = CloudChaser.NET_BASE_SIZE

    SEND_MAX = CloudChaser.NET_SEND_MAX

    EVNT_PEER = CloudChaser.NET_EVNT_PEER
    EVNT_PEER_SET = CloudChaser.NET_EVNT_PEER_SET
    EVNT_PEER_EXP = CloudChaser.NET_EVNT_PEER_EXP
    EVNT_PEER_OUT = CloudChaser.NET_EVNT_PEER_OUT
    EVNT_PEER_UPD = CloudChaser.NET_EVNT_PEER_UPD

    CHANNEL_COUNT = CloudChaser.PHY_CHAN_COUNT

    device = None
    cc = None
    stats = None

    __addr = None
    __cell = None

    __recv_q = None
    __recv_mac_q = None
    __evnt_q = None

    __status_last = None

    __instance = {}

    def __new__(cls, device, stats=None):
        return CCRF.__instance.setdefault(device, object.__new__(cls))

    def __init__(self, device, stats=None):
        self.__recv_q = AsyncQ(size=64000)
        self.__recv_mac_q = AsyncQ(size=64000)
        self.__evnt_q = AsyncQ(size=64000)

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

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def open(self):
        """Open the serial connection.
        """
        self.cc.open(self.device)

    def close(self):
        """Close the serial connection to the device.
        """
        self.cc.close()

    def reset(self, reopen=False):
        """Reset and optionally re-open the device.
        """
        return self.cc.reset(reopen=reopen)

    def __load_status(self):
        self.__status_last = self.cc.io.status()
        self.__addr = self.__status_last.addr
        self.__cell = self.__status_last.cell

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

    def print_status(self, status=None, file=sys.stderr, end=os.linesep*2):
        """Shortcut to [retrieve and] print current status.
        """
        print(self.format_status(status), file=file, end=end)

    def addr(self):
        """Get the device network address.
        """
        if not self.__addr:
            self.__load_status()
        return self.__addr
    
    def cell(self):
        """Get the device cell.
        """
        if not self.__cell:
            self.__load_status()
        return self.__cell

    def cell_set(self, addr, orig, cell):
        """Set the device cell address.
        :param addr: Current device address.
        :param orig: Current device cell.
        :param cell: Desired new cell.
        :return: Actual new cell or 0 for error.
        """
        rslt = self.cc.io.config_cell(addr, orig, cell)
        self.__clear_status()
        return rslt

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

    def rainbow(self, addr=ADDR_NONE):
        """Flashes the onboard RGB LEDs in a rainbow pattern, optionally remotely.
        """
        self.cc.io.rainbow(addr)

    def update(self, size_total, size_header, size_user, size_code, size_text, size_data, bin_data):
        """Update device flash.

        :param size_total: Total size of the flash data.
        :param size_header: Flash header size (interrupts + ram).
        :param size_user: User data ROM section size (max 4K).
        :param size_code: Fast code ROM section size.
        :param size_text: Text (ROM code) section size.
        :param size_data: Data ROM section size.
        :param bin_data: All the data.
        :return: Integer, zero on success.
        """
        return self.cc.io.updt(size_total, size_header, size_user, size_code, size_text, size_data, bin_data)

    def fota(self, addr):
        """Flash current firmware over the air to another device.

        :param addr: Address to send firmware.
        :return: True if apparent success (all data sent).
        """
        return self.cc.io.fota(addr)

    def send(self, addr, port, typ, data=b'', mesg=False, wait=False):
        """Send a simple datagram message.

        :param addr: Destination node address.
        :param port: Destination port number.
        :param typ: User type identifier.
        :param data: Data to send.
        :param mesg: Request ACK.
        :param wait: Wait for tx done (or ACK if mesg).
        """
        return self.cc.io.send(addr, port, typ, data, mesg, wait)

    def send_mac(self, typ, dest, data, node=0, wait=False):
        """Send a MAC-layer datagram.

        :param typ: MAC message type: CCRF.MAC_DGRM, CCRF.MAC_MESG, or CCRF.MAC_STRM.
        :param dest: Destination node address.
        :param data: Data to send.
        :param node: Source address (0 for default).
        :param wait: Wait until TX complete to return.
        """
        if wait:
            return self.cc.io.mac_send_wait(typ, dest, data, node)

        return self.cc.io.mac_send(typ, dest, data, node)

    def mesg(self, addr, port, typ, data=b'', wait=True):
        """Send a message and await ACK.

        :param addr: Destination node address.
        :param port: Destination port number.
        :param typ: User type identifier.
        :param data: Data to send.
        :param wait: Wait for ACK (default true).
        :return: Number of packets ACKed.
        """
        return self.cc.io.mesg(addr, port, typ, data, wait)

    def evnt(self, once=False, timeout=None):
        """Receive events.
        :param once: finish receiving after one message.
        :param timeout: timeout in seconds or None.
        :return: Iterater of adict(event,data).
        """
        return self.__evnt_q.recv(once, timeout)

    def recv(self, addr=None, dest=None, port=None, typ=None, once=False, timeout=None):
        """Receive messages (iterator).

        :param addr: filter by address.
        :param dest: filter by destination (this device or broadcast).
        :param port: filter by port.
        :param typ: filter by type.
        :param once: finish receiving after one message.
        :param timeout: timeout in seconds or None.
        :return: iterator that receives once or forever.
        """
        for mesg in self.__recv_q.recv(once=False, timeout=timeout):

            if addr is not None and mesg.addr != addr:
                continue

            if dest is not None and mesg.dest != dest:
                continue

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

        :return: adict{node, time, peers=adict{addr, last, rssi, lqi, version, date, time}}.
        """
        return self.cc.io.peer()

    def ping(self, addr, timeout=100, size=0, size_resp=0, stream=False):
        """Ping another device.

        :param addr: Address to ping (cannot be broadcast, use trxn instead).
        :param timeout: Timeout in milliseconds.
        :param size: Size of ping packet.
        :param size_resp: Size of ping reply packet.
        :param stream: Send stream packets (no CCA).
        :return: adict{addr, rtt_usec, meta{locl{rssi, lqi}, peer{rssi, lqi}}}
        """
        return self.cc.io.ping(addr, timeout, size, size_resp, strm=stream)

    def __handle_recv(self, addr, dest, port, typ, data):
        self.__recv_q.push(adict(
            addr=addr, dest=dest, port=port, type=typ, data=data
        ), timeout=0)

    def __handle_recv_mac(self, addr, peer, dest, rssi, lqi, data):
        self.__recv_mac_q.push(adict(
            addr=addr, peer=peer, dest=dest, rssi=rssi, lqi=lqi, data=data
        ), timeout=0)

    def __handle_evnt(self, evnt):
        self.__evnt_q.push(evnt, timeout=0)

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

        parser_rainbow.add_argument(
            'addr',
            nargs='?',
            type=lambda p: int(p, 16),
            default=CCRF.ADDR_NONE,
            help='device address to make flash.'
        )

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
        parser_send.add_argument(
            '-l', '--tx-lines',
            action="store_true",
            help='add newline after each -tx.'
        )
        parser_send.add_argument(
            '-L', '--tx-line',
            action="store_true",
            help='newline after last -tx.'
        )
        parser_send.add_argument(
            '-ei', '--exec-in',
            type=lambda p: [pi.strip() for pi in p.split()],
            help='execute program and pipe stdout over rf.'
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
            '-n', '--mesg-newline',
            action="store_true",
            help='newline after each message on output.'
        )
        parser_recv.add_argument(
            '-N', '--newline',
            action="store_true",
            help='newline at end of output.'
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
            '-F', '--no-flush',
            action="store_true",
            default=False,
            help='do not flush output on each receive.'
        )
        parser_recv.add_argument(
            '-eo', '--exec-out',
            type=lambda p: [pi.strip() for pi in p.split()],
            help='execute program and pipe to stdin from rf.'
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
            '-n', '--mesg-newline',
            action="store_true",
            help='newline after each message on ouptut.'
        )
        parser_rxtx.add_argument(
            '-N', '--newline',
            action="store_true",
            help='newline at end of output.'
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
            '-F', '--no-flush',
            action="store_true",
            default=False,
            help='do not flush output on each receive.'
        )
        parser_rxtx.add_argument(
            '-tx', '--data',
            type=lambda p: bytes(p, 'ascii'),
            action='append',
            default=[],
            help='data to send (before input if given, otherwise -I implied).'
        )
        parser_rxtx.add_argument(
            '-l', '--tx-lines',
            action="store_true",
            help='add newline after each -tx.'
        )
        parser_rxtx.add_argument(
            '-L', '--tx-line',
            action="store_true",
            help='newline after last -tx.'
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
        parser_addr.add_argument('-c', '--cell', action='store_true', help='include cell in output.')
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
        
        parser_cell = subparsers.add_parser('cell', help='show [and set] device cell and address.')
        parser_cell.add_argument('-q', '--quiet', action='store_true', help='do not print anything.')
        parser_cell.add_argument(
            'orig',
            nargs='?',
            metavar="CELL:ORIG",
            type=lambda p: tuple(int(m, 16) for m in p.split(':', 1)),
            default=(None, None),
            help='current device cell and address.'
        )
        parser_cell.add_argument(
            'cell',
            nargs='?',
            metavar="CELL[:ADDR]",
            type=lambda p: tuple(int(m, 16) for m in p.split(':', 1)) if ':' in p else (int(p, 16), None),
            default=(None, None),
            help='new device cell and optional new address.'
        )

        parser_monitor = subparsers.add_parser('monitor', help='monitor i/o stats')

        parser_flush = subparsers.add_parser('flush', help='flush device input buffer')

        parser_reset = subparsers.add_parser('reset', help='reset the device')

        parser_fota = subparsers.add_parser('fota', help='flash over the air')

        parser_fota.add_argument(
            'addr',
            type=lambda p: int(p, 16) if p.lower() != "auto" else "auto",
            help='address to send current firmware, or "auto" to bring all peers up to date.'
        )

        parser_update = subparsers.add_parser('update', aliases=['up'], help='flash new firmware')
        CCRF._command_up = CCRF._command_update

        default_update_path = os.path.relpath(
            os.path.abspath(os.path.join(os.path.dirname(__file__), "../../build/release")),
            os.getcwd()
        )

        parser_update.add_argument(
            '-p', '--path',
            default=default_update_path,
            help=f"path to firmware package files: default={default_update_path}"
        )

        parser_ping = subparsers.add_parser('ping', help='ping remote device')

        parser_ping.add_argument(
            'addr',
            type=lambda a: int(a, 16),
            help='device address to ping.'
        )

        parser_ping.add_argument(
            '-t', '--timeout',
            metavar='<ms>',
            type=int,
            default=1000,
            help="timeout in ms (default: 1000)."
        )

        parser_ping.add_argument(
            '-i', '--interval',
            metavar='<ms>',
            type=int,
            default=1000,
            help="time in between pings (default: 1000ms)."
        )

        parser_ping.add_argument(
            '-c', '--count',
            metavar='#',
            type=int,
            default=1,
            help="ping count (default: 1)."
        )

        parser_ping.add_argument(
            '-f', '--forever',
            action='store_true',
            default=False,
            help="shorthand for --count=0."
        )

        parser_ping.add_argument(
            '-st', '--stream',
            action='store_true',
            default=False,
            help="send stream packets (no CCA)."
        )

        parser_ping.add_argument(
            '-s', '--size',
            metavar='<sz>',
            type=int,
            default=0,
            help="ping packet size (default: 0)."
        )

        parser_ping.add_argument(
            '-r', '--size-repl',
            metavar='<sz>',
            type=int,
            default=0,
            help="reply packet size (default: 0)."
        )

        parser_ping.add_argument(
            '-S', '--size-both',
            metavar='<sz>',
            type=int,
            default=0,
            help="short for -s=<sz> -r=<sz>."
        )

        argcomplete.autocomplete(parser)
        args = parser.parse_args()

        try:
            with CCRF(args.device, stats=sys.stderr if args.command == 'monitor' else None) as ccrf:
                command = getattr(CCRF, f"_command_{args.command}")
                command(ccrf, args)

        except KeyboardInterrupt:
            exit(os.linesep)

    @staticmethod
    def _command_status(ccrf, args):
        stat = ccrf.status()
        print(ccrf.format_status(stat), file=sys.stderr)

        if args.verbose:
            print()

            print("mac: rx={}/{}/{} tx={}/{}/{} stack: {}".format(
                stat.mac_stat.recv.count, stat.mac_stat.recv.size, stat.mac_stat.recv.error,
                stat.mac_stat.send.count, stat.mac_stat.send.size, stat.mac_stat.send.error,
                stat.mac_su_rx
            ))

            print("phy: rx={}/{}/{} tx={}/{}/{} stack: {}".format(
                stat.phy_stat.recv.count, stat.phy_stat.recv.size, stat.phy_stat.recv.error,
                stat.phy_stat.send.count, stat.phy_stat.send.size, stat.phy_stat.send.error,
                stat.phy_su
            ))

            print("heap: free={} usage={}".format(stat.heap_free, stat.heap_usage))
            print()

            print("chan  hop    freq (hz)    rssi    prev")

            for chan in stat.chan:
                print(f"{chan.id:02d}    {chan.id_hop:02d}     {chan.freq:>9}    {chan.rssi:>4}    {chan.rssi_prev:>4}")

    @staticmethod
    def _command_echo(ccrf, args):

        if args.data == '-':
            while sys.stdin.readable():
                ccrf.echo(sys.stdin.read())

        else:
            print(ccrf.echo(args.data))

        time.sleep(0.100)

    @staticmethod
    def _command_flush(ccrf, args):
        ccrf.cc.flush()
        time.sleep(0.100)

    @staticmethod
    def _command_reset(ccrf, args):
        ccrf.reset(reopen=False)
        time.sleep(0.100)

    @staticmethod
    def _command_fota(ccrf, args, peer=None):
        stat = ccrf.status()

        if not peer:
            ccrf.print_status(stat)

        if args.addr is "auto":
            for peer in ccrf.peers().peers:
                if peer.last < 30 and peer.date < stat.date:
                    args.addr = peer.addr
                    CCRF._command_fota(ccrf, args, peer)
            return

        if args.addr == CCRF.ADDR_NONE or args.addr == CCRF.ADDR_BCST:
            exit("invalid address.")

        print(f"fota: {args.addr:04x} ... ", end='')

        sys.stdout.flush()

        if peer is None:
            peers = tuple(filter(lambda p: p.addr == args.addr, ccrf.peers().peers))

            if len(peers) != 1:
                exit("peer not found.")

            peer = peers[0]

        print(f"{peer.version:08x}@{CloudChaser.format_date(peer.date)} -> {stat.version:08x}@{CloudChaser.format_date(stat.date)} ... ", end='')

        sys.stdout.flush()

        if ccrf.fota(args.addr):
            print("sent.")
        else:
            print("fail.")

    @staticmethod
    def _command_update(ccrf, args):
        sizes = open(os.path.join(args.path, "fw.siz")).read()

        size_interrupts = int(re.findall(r"^\.interrupts\s+(\d+).+$", sizes, flags=re.MULTILINE)[0])
        size_config = int(re.findall(r"^\.flash_config\s+(\d+).+$", sizes, flags=re.MULTILINE)[0])
        size_user = int(re.findall(r"^\.user_rom\s+(\d+).+$", sizes, flags=re.MULTILINE)[0])
        size_code = int(re.findall(r"^\.fast_code\s+(\d+).+$", sizes, flags=re.MULTILINE)[0])
        size_text = int(re.findall(r"^\.text\s+(\d+).+$", sizes, flags=re.MULTILINE)[0])
        size_data = int(re.findall(r"^\.data\s+(\d+).+$", sizes, flags=re.MULTILINE)[0])

        size_total = size_interrupts + size_config + size_user + size_code + size_text + size_data

        bin_file = os.path.join(args.path, "fw.bin")
        bin_file_size = os.path.getsize(bin_file)

        if bin_file_size != size_total:
            print(f"update: bin size of {bin_file_size} doesn't match section sizes ({size_total})!")
            exit(-1)

        bin_data = open(bin_file, 'rb').read()

        rslt = ccrf.update(size_total, size_interrupts + size_config, size_user, size_code, size_text, size_data, bin_data)

        if rslt == 0:
            print("update successful, closing.", file=sys.stderr)
            ccrf.close()

    @staticmethod
    def _command_rainbow(ccrf, args):
        ccrf.rainbow(args.addr)
        time.sleep(0.1)

    @staticmethod
    def _command_addr(ccrf, args):
        addr = ccrf.addr()

        if args.orig:
            if not args.addr:
                raise argparse.ArgumentError("addr is required.")

            addr = ccrf.addr_set(args.orig, args.addr)

        if not args.quiet:
            if args.cell:
                print(f"{ccrf.cell():02X}:{addr if addr else ccrf.addr():04X}")
            else:
                print(f"{addr if addr else ccrf.addr():04X}")

        exit(addr != ccrf.addr())

    @staticmethod
    def _command_cell(ccrf, args):
        addr = ccrf.addr()
        cell = ccrf.cell()

        cell_orig, addr_orig = args.orig
        cell_new, addr_new = args.cell

        if cell_orig:
            if not cell_new:
                raise argparse.ArgumentError("cell is required.")

            cell_new = ccrf.cell_set(addr_orig, cell_orig, cell_new)

            if cell_new:
                cell = cell_new

                if addr_new:
                    time.sleep(0.100)
                    addr = ccrf.addr_set(addr_orig, addr_new)

        if not args.quiet:
            print(f"{cell if cell else ccrf.cell():02X}:{addr if addr else ccrf.addr():04X}")

        exit(cell != ccrf.cell() or addr != ccrf.addr())

    @staticmethod
    def _command_peer(ccrf, args):
        ccrf.print_status()

        peer_info = ccrf.peers()

        for peer in peer_info.peers:
            vi = f"  v: {peer.version:08x}.{CloudChaser.format_date(peer.date)}  t: {str(peer.time) + 's':<7}" if peer.time else ""

            print(
                f"{peer.addr:04X}{vi}  l: {peer.last:<2}   q: {peer.lqi:<2}  r: {peer.rssi:<4}",
                file=sys.stderr
            )

    @staticmethod
    def _command_ping(ccrf, args):
        if args.addr == CCRF.ADDR_NONE or args.addr == CCRF.ADDR_BCST:
            exit("invalid address.")

        if args.forever:
            args.count = 0
        elif args.count == 0:
            args.forever = True

        if args.size_both:
            args.size = args.size_repl = args.size_both

        while args.forever or args.count:
            print(f"ping {args.addr:04X}{('    sz: ' + str(args.size)) if args.size else ''}", end='')
            sys.stdout.flush()

            rslt = ccrf.ping(args.addr, args.timeout, args.size, args.size_repl, stream=args.stream)

            if rslt.tx_count != 1:
                print(f"/{rslt.tx_count}", end='')

            print(f"    ", end='')

            if rslt.rtt_usec:
                rsiq = f"{rslt.meta.locl.rssi}/{rslt.meta.locl.lqi}"
                priq = f"{rslt.meta.peer.rssi}/{rslt.meta.peer.lqi}"
                stat = f"rsiq: {rsiq:<7}  priq: {priq:<7}  rtt: {rslt.rtt_usec}us    "

                if args.size_repl:
                    stat += f"sz: {args.size_repl}"

            else:
                stat = "fail."

            print(stat)

            if (not args.forever) and args.count:
                args.count -= 1

            if args.interval and (args.forever or args.count):
                time.sleep(args.interval / 1000.0)

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

                CCRF._command_peer(ccrf, args)
            else:
                print(f"event: {evnt.id} data={evnt.data}")

    @staticmethod
    def _command_send(ccrf, args, *, rxtx=False):
        if rxtx:
            def done(r): return r
        else:
            done = exit

        if args.exec_in:
            if args.input != sys.stdin or args.no_input:
                raise ValueError("cannot specify input when using pipe")

            spi = subprocess.Popen(
                args=args.exec_in, executable=args.exec_in[0],
                stdin=sys.stdin, stdout=subprocess.PIPE,
                stderr=sys.stderr
            )

            args.input = spi.stdout

        if args.mesg and not args.dest:
            return done("error: mesg requires destination")

        if args.no_input:
            args.input = None
        elif type(args.input) is str:
            size = os.path.getsize(args.input)

            if size > 16384 and args.split < 0:
                print(f"{args.input}: splitting {size} bytes into 16K chunks", file=sys.stderr)
                args.split = 16384

        result = 0

        path = args.path_dest if rxtx else args.path

        for data in args.data:
            if (args.tx_lines or (args.tx_line and data == args.data[-1])) and not data.endswith(bytes(os.linesep, 'ascii')):
                data += bytes(os.linesep, 'ascii')

            rslt = ccrf.send(args.dest, path[0], path[1], data, mesg=args.mesg, wait=True)

            if type(rslt) is int:
                result += rslt

        if args.verbose and not args.input and not args.data:
            return done("warning: nothing sent")

        if not args.input or (args.input == sys.stdin and args.data):
            return done(result)

        inf = open(args.input, 'rb') if isinstance(args.input, str) else args.input

        read = inf.buffer.read if hasattr(inf, 'buffer') else inf.read

        try:
            while inf.readable():
                data = read(args.split)

                if data:
                    sent = ccrf.send(args.dest, path[0], path[1], data, mesg=args.mesg, wait=args.mesg)

                    if args.verbose:
                        CCRF.__print_mesg(ccrf.addr(), args.dest, path[0], path[1], data)

                    if type(sent) is int:
                        result += sent
                else:
                    break

        except IOError:
            pass

        return done(result)

    @staticmethod
    def _command_recv(ccrf, args):

        if args.exec_out:
            if args.out != sys.stdout:
                raise ValueError("cannot specify output when using pipe")

            spo = subprocess.Popen(
                args=args.exec_out, executable=args.exec_out[0],
                stdin=subprocess.PIPE, stdout=sys.stdout,
                stderr=sys.stderr
            )

            args.out = spo.stdin

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
                    elif args.bcast and mesg.dest != CCRF.ADDR_BCST:
                        continue

                    if args.source and mesg.addr != args.source:
                        continue

                    if args.mesg_newline and not mesg.data.endswith(bytes(os.linesep, 'ascii')):
                        mesg.data += bytes(os.linesep, 'ascii')

                    write(mesg.data)

                    if not args.no_flush:
                        out.flush()

                    if args.verbose:
                        CCRF.__print_mesg(mesg.addr, mesg.dest, mesg.port, mesg.type, mesg.data)

                    if args.respond:
                        if args.no_flush:
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
            if args.newline:
                write(bytes(os.linesep, 'ascii'))

                if not args.no_flush:
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

            if args.exec_in or args.exec_out:
                raise ValueError("cannot specify -ei or -eo with -e.")

            sp = subprocess.Popen(
                args=args.exec, executable=args.exec[0],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=sys.stderr
            )

            args.input = sp.stdout
            args.out = sp.stdin

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
