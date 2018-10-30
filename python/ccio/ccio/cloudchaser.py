"""Cloud Chaser Support Library
"""
import os
import sys
import struct
import time
import random
import threading
import traceback

from .serf import Serf
from .util import adict


class CloudChaser(Serf):
    CODE_ID_ECHO = 0
    CODE_ID_STATUS = 1
    CODE_ID_MAC_SEND = 2
    CODE_ID_MAC_RECV = 3
    CODE_ID_SEND = 4
    CODE_ID_MESG = 5
    CODE_ID_MESG_SENT = 5
    CODE_ID_RECV = 6
    CODE_ID_TRXN = 7
    CODE_ID_RESP = 8
    CODE_ID_EVNT = 9
    CODE_ID_PEER = 10
    CODE_ID_RESET = 17
    CODE_ID_UART = 26
    CODE_ID_LED = 27
    CODE_ID_RAINBOW = 29

    NET_EVNT_PEER = 0
    NET_EVNT_PEER_SET = 0
    NET_EVNT_PEER_EXP = 1

    NET_ADDR_BCST = 0
    NET_ADDR_MASK = 0xFFFF

    NET_PORT_MASK = 0b1111111111
    NET_TYPE_MASK = 0b1111

    RESET_MAGIC = 0xD1E00D1E

    NMAC_SEND_DGRM = 0
    NMAC_SEND_MESG = 1
    NMAC_SEND_TRXN = 2
    NMAC_SEND_STRM = 3

    __CODE_SEND_WAIT = 1

    def __init__(self, stats=None, handler=None, evnt_handler=None, mac_handler=None, uart_handler=None):
        super(CloudChaser, self).__init__()
        
        self.stats = stats
        self.handlers = [handler] if handler else []
        self.evnt_handlers = [evnt_handler] if evnt_handler else []
        self.mac_handlers = [mac_handler] if mac_handler else []
        self.uart_handlers = [uart_handler] if uart_handler else []

        self.add(
            name='echo',
            code=CloudChaser.CODE_ID_ECHO,
            encode=lambda mesg: struct.pack(f"<{len(mesg) + 1}s", mesg + b'\x00'),
            decode=lambda data: [str(data, 'ascii')],
            handle=lambda mesg: sys.stdout.write(mesg)
        )

        self.add(
            name='reset',
            code=CloudChaser.CODE_ID_RESET,
            encode=lambda: struct.pack("<I", CloudChaser.RESET_MAGIC)
        )

        def decode_status(data):
            version, serial, uptime, addr, cell, rdid, phy_su, mac_su_tx, mac_su_rx, heap_free, heap_usage, data = \
                struct.unpack(f"<IQIHBBIIIII{len(data) - 40}s", data)

            def decode_status_set(dat):
                recv_count, recv_size, recv_error, dat = struct.unpack(f"<III{len(dat) - 12}s", dat)
                send_count, send_size, send_error, dat = struct.unpack(f"<III{len(dat) - 12}s", dat)

                return adict(
                    recv=adict(count=recv_count, size=recv_size, error=recv_error),
                    send=adict(count=send_count, size=send_size, error=send_error)
                ), dat

            phy_stat, data = decode_status_set(data)
            mac_stat, data = decode_status_set(data)
            net_stat, data = decode_status_set(data)

            return [adict(
                version=version, serial=serial, uptime=uptime, addr=addr, cell=cell, rdid=rdid,
                phy_su=phy_su, mac_su_tx=mac_su_tx, mac_su_rx=mac_su_rx,
                heap_free=heap_free, heap_usage=heap_usage,
                phy_stat=phy_stat, mac_stat=mac_stat, net_stat=net_stat
            )]

        self.add(
            name='status',
            code=CloudChaser.CODE_ID_STATUS,
            decode=decode_status,
            response=CloudChaser.CODE_ID_STATUS
        )

        self.add(
            name='mac_recv',
            code=CloudChaser.CODE_ID_MAC_RECV,
            decode=lambda data: struct.unpack(f"<HHHHbB{len(data) - 10}s", data),
            handle=self.handle_mac_recv
        )

        self.add(
            name='mac_send',
            code=CloudChaser.CODE_ID_MAC_SEND,
            encode=lambda typ, dest, data, flag=0, addr=0: struct.pack(
                f"<BBHHH{len(data)}s", typ & 0xFF, (flag & ~CloudChaser.__CODE_SEND_WAIT) & 0xFF, addr & 0xFFFF, dest & 0xFFFF, len(data), data
            )
        )

        self.add(
            name='mac_send_wait',
            code=CloudChaser.CODE_ID_MAC_SEND,
            encode=lambda typ, dest, data, flag=0, addr=0: struct.pack(
                f"<BBHHH{len(data)}s" , typ & 0xFF, (flag | CloudChaser.__CODE_SEND_WAIT) & 0xFF, addr & 0xFFFF,
                dest & 0xFFFF, len(data), data
            ),
            decode=lambda data: struct.unpack("<HI", data),
            response=CloudChaser.CODE_ID_MAC_SEND
        )

        def encode_send(addr, port, typ, data, wait=None):
            if port & (~self.NET_PORT_MASK & 0xFFFF):
                raise ValueError("port uses restricted bits")
            if typ & (~self.NET_TYPE_MASK & 0xFFFF):
                raise ValueError("typ uses restricted bits")

            if wait is None:
                return struct.pack(
                    f"<HHB{len(data)}s", addr & CloudChaser.NET_ADDR_MASK,
                    port & CloudChaser.NET_PORT_MASK,
                    typ & CloudChaser.NET_TYPE_MASK, data
                )
            else:
                return struct.pack(
                    f"<HHBI{len(data)}s", addr & CloudChaser.NET_ADDR_MASK,
                    port & CloudChaser.NET_PORT_MASK,
                    typ & CloudChaser.NET_TYPE_MASK,
                    wait & 0xFFFFFFFF, data
                )

        self.add(
            name='send',
            code=CloudChaser.CODE_ID_SEND,
            encode=lambda addr, port, typ, data: encode_send(addr, port, typ, data)
        )

        self.add(
            name='mesg',
            code=CloudChaser.CODE_ID_MESG,
            encode=lambda addr, port, typ, data: encode_send(addr, port, typ, data),
            decode=lambda data: struct.unpack("<H", data),
            response=CloudChaser.CODE_ID_MESG_SENT
        )

        self.add(
            name='resp',
            code=CloudChaser.CODE_ID_RESP,
            encode=lambda addr, port, typ, data: struct.pack(
                f"<HHB{len(data)}s", addr & 0xFFFF, port & 0xFFFF, typ & 0xFF, data
            )
        )

        self.add(
            name='recv',
            code=CloudChaser.CODE_ID_RECV,
            decode=lambda data: struct.unpack(f"<HHHB{len(data) - 7}s", data),
            handle=self.handle_recv
        )

        def decode_trxn_stat(data):
            addr, port, typ, data = struct.unpack(f"<HHB{len(data) - 5}s", data)
            # TODO: Validate/match port & type
            return None if not addr else (addr, data)

        self.add(
            name='trxn',
            code=CloudChaser.CODE_ID_TRXN,
            encode=lambda addr, port, typ, wait, data: encode_send(addr, port, typ, data, wait),
            decode=decode_trxn_stat,
            response=CloudChaser.CODE_ID_TRXN,
            multi=True
        )

        def decode_peer(data):
            addr, now, data = struct.unpack(f"<HI{len(data) - 6}s", data)

            peers = []

            while len(data) >= 10:
                addri, peer, last, rssi, lqi, data = struct.unpack(f"<HHIbB{len(data) - 10}s", data)
                # TODO: This is a good place for collections.namedtuple
                peers.append((addri, peer, last, rssi, lqi))

            return addr, now, peers

        self.add(
            name='peer',
            code=CloudChaser.CODE_ID_PEER,
            decode=decode_peer,
            response=CloudChaser.CODE_ID_PEER
        )

        def decode_evnt(data):
            event, data = struct.unpack(f"<B{len(data) - 1}s", data)

            if event == CloudChaser.NET_EVNT_PEER:
                data = struct.unpack("<HB", data)

            return event, data

        self.add(
            name='evnt',
            code=CloudChaser.CODE_ID_EVNT,
            decode=decode_evnt,
            handle=self.handle_evnt
        )

        self.add(
            name='uart',
            code=CloudChaser.CODE_ID_UART,
            encode=lambda data: data,
            decode=lambda data: [data],
            handle=self.handle_uart
        )

        self.add(
            name='rainbow',
            code=CloudChaser.CODE_ID_RAINBOW
        )

        self.add(
            name='led',
            code=CloudChaser.CODE_ID_LED,
            encode=lambda addr, mask, rgb: struct.pack(
                f"<HB{len(rgb * 3)}s", addr & 0xFFFF, mask & 0xFF,
                ''.join(chr(c) for grb in [(g, r, b) for r, g, b in rgb] for c in grb)  # Rearrange and unroll
            )
        )

    def __str__(self):
        return "cc@{}".format(self.port)

    def reset(self, reopen=True):
        self.io.reset()

        if reopen:
            self.reopen()
        else:
            self.close()

    @staticmethod
    def format_status(stat):
        return "Cloud Chaser {:016X}@{:04X} up={}s rx={}/{}/{} tx={}/{}/{}".format(
            stat.serial, stat.addr, stat.uptime // 1000,
            stat.net_stat.recv.count, stat.net_stat.recv.size, stat.net_stat.recv.error,
            stat.net_stat.send.count, stat.net_stat.send.size, stat.net_stat.send.error
        )

    def handle_mac_recv(self, addr, peer, dest, size, rssi, lqi, data):
        if self.stats is not None:
            self.stats.lock()
            if not self.stats.recv_count:
                self.stats.recv_time = time.time()
    
            self.stats.recv_size += len(data)
            self.stats.recv_count += 1
            self.stats.rssi_sum += rssi
            self.stats.lqi_sum += lqi
            self.stats.unlock()

        for mac_handler in self.mac_handlers:
            mac_handler(self, addr, peer, dest, rssi, lqi, data)

    def handle_recv(self, addr, dest, port, typ, data):
        if self.stats is not None:
            self.stats.lock()
            if not self.stats.recv_count:
                self.stats.recv_time = time.time()

            self.stats.recv_size += len(data)
            self.stats.recv_count += 1
            self.stats.unlock()

        for handler in self.handlers:
            handler(self, addr, dest, port, typ, data)

    def handle_evnt(self, event, data):
        for evnt_handler in self.evnt_handlers:
            evnt_handler(self, event, data)

    def handle_uart(self, data):
        for uart_handler in self.uart_handlers:
            uart_handler(self, data)
