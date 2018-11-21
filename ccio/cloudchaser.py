"""Cloud Chaser Support Library
"""
import sys
import struct
import time
from datetime import datetime

from .serf import Serf
from .util import adict


CODE_ID_ECHO = 0
CODE_ID_STATUS = 1
CODE_ID_CONFIG = 30
CODE_ID_CONFIG_RSP = 31
CODE_ID_MAC_SEND = 2
CODE_ID_MAC_RECV = 3
CODE_ID_SEND = 4
CODE_ID_SEND_DONE = 5
CODE_ID_RECV = 6
CODE_ID_TRXN = 7
CODE_ID_RESP = 8
CODE_ID_EVNT = 9
CODE_ID_PEER = 10
CODE_ID_RESET = 17
CODE_ID_FLASH = 21
CODE_ID_FLASH_STAT = 21
CODE_ID_UART = 26
CODE_ID_LED = 27
CODE_ID_RAINBOW = 29

_CODE_CONFIG_ID_ADDR = 0xADD1
_CODE_CONFIG_ID_CELL = 0xCE11

_CODE_CONFIG_RSLT_OK = 1
_CODE_CONFIG_RSLT_ERR = 0

_CODE_SEND_MESG = 0b01
_CODE_SEND_RSLT = 0b10

_CODE_MAC_SEND_WAIT = 1

_RESET_MAGIC = 0xD1E00D1E


class CloudChaser(Serf):

    NET_EVNT_PEER = 0
    NET_EVNT_PEER_SET = 0
    NET_EVNT_PEER_EXP = 1
    NET_EVNT_PEER_OUT = 2
    NET_EVNT_PEER_UPD = 3

    NET_BASE_SIZE = 113

    NET_SEND_MAX = 0xFFFA

    NET_ADDR_BCST = 0
    NET_ADDR_MASK = 0xFFFF
    NET_ADDR_BITS = 16
    NET_ADDR_INVL = NET_ADDR_MASK
    NET_CELL_MASK = 0xFF
    NET_CELL_BITS = 8

    NET_PORT_MASK = 0b1111111111  # 0x3FF, 1023
    NET_TYPE_MASK = 0b1111  # 0xF, 15

    NMAC_SEND_DGRM = 0
    NMAC_SEND_MESG = 1
    NMAC_SEND_TRXN = 2
    NMAC_SEND_STRM = 3

    NMAC_FLAG_MASK = ~_CODE_MAC_SEND_WAIT & 0xFF

    PHY_CHAN_COUNT = 25

    def __init__(self, stats=None, handler=None, evnt_handler=None, mac_handler=None, uart_handler=None):
        super(CloudChaser, self).__init__()
        
        self.stats = stats
        self.handlers = [handler] if handler else []
        self.evnt_handlers = [evnt_handler] if evnt_handler else []
        self.mac_handlers = [mac_handler] if mac_handler else []
        self.uart_handlers = [uart_handler] if uart_handler else []

        self.add(
            name='echo',
            code=CODE_ID_ECHO,
            encode=lambda mesg: struct.pack(f"<{len(mesg) + 1}s", mesg + b'\x00'),
            decode=lambda data: str(data, 'ascii'),
            response=CODE_ID_ECHO
        )

        self.add(
            name='reset',
            code=CODE_ID_RESET,
            encode=lambda: struct.pack("<I", _RESET_MAGIC)
        )

        def decode_status(data):
            version, date, serial, uptime, addr, cell, rdid, phy_su, mac_su_rx, heap_free, heap_usage, data = \
                struct.unpack(f"<IIQIHBBIIII{len(data) - 40}s", data)

            def decode_status_set(d):
                recv_count, recv_size, recv_error, d = struct.unpack(f"<III{len(d) - 12}s", d)
                send_count, send_size, send_error, d = struct.unpack(f"<III{len(d) - 12}s", d)

                return adict(
                    recv=adict(count=recv_count, size=recv_size, error=recv_error),
                    send=adict(count=send_count, size=send_size, error=send_error)
                ), d

            phy_stat, data = decode_status_set(data)
            mac_stat, data = decode_status_set(data)
            net_stat, data = decode_status_set(data)

            chan = []

            for chan_id in range(CloudChaser.PHY_CHAN_COUNT):
                freq, hop_id, rssi, rssi_prev, data = struct.unpack(f"<IHbb{len(data) - 8}s", data)
                chan.append(adict(
                    id=chan_id,
                    id_hop=hop_id,
                    freq=freq,
                    rssi=rssi,
                    rssi_prev=rssi_prev
                ))

            return adict(
                version=version, date=date, serial=serial,
                uptime=uptime, addr=addr, cell=cell, rdid=rdid,
                phy_su=phy_su, mac_su_rx=mac_su_rx,
                heap_free=heap_free, heap_usage=heap_usage,
                phy_stat=phy_stat, mac_stat=mac_stat, net_stat=net_stat,
                chan=tuple(chan)
            )

        self.add(
            name='status',
            code=CODE_ID_STATUS,
            decode=decode_status,
            response=CODE_ID_STATUS
        )

        def encode_config(cid, param, data=b''):
            if isinstance(param, int):
                return struct.pack(f"<II{len(data)}s", cid & 0xFFFFFFFF, param & 0xFFFFFFFF, data)

            assert isinstance(param, (bytes, bytearray))
            return struct.pack(f"<I4s{len(data)}s", cid & 0xFFFFFFFF, param, data)

        self.add(
            name='config',
            code=CODE_ID_CONFIG,
            encode=encode_config,
            decode=lambda data: struct.unpack("<I", data)[0],
            response=CODE_ID_CONFIG_RSP
        )

        def config_addr(orig, addr):
            return self.io.config(
                _CODE_CONFIG_ID_ADDR,
                struct.pack("<HH", orig & CloudChaser.NET_ADDR_MASK, addr & CloudChaser.NET_ADDR_MASK)
            )

        self.io.config_addr = config_addr

        def config_cell(addr, orig, cell):
            return self.io.config(
                _CODE_CONFIG_ID_CELL,
                struct.pack("<HBB", addr & CloudChaser.NET_ADDR_MASK, orig & CloudChaser.NET_CELL_MASK, cell & CloudChaser.NET_CELL_MASK)
            )

        self.io.config_cell = config_cell

        def encode_send(addr, port, typ, data, mesg=False, wait=None, rslt=False):
            if (port & self.NET_PORT_MASK) != port:
                raise ValueError("port uses restricted bits")
            if (typ & self.NET_PORT_MASK) != typ:
                raise ValueError("typ uses restricted bits")

            if wait is None:
                return struct.pack(
                    f"<HHBB{len(data)}s", addr & CloudChaser.NET_ADDR_MASK,
                    port & CloudChaser.NET_PORT_MASK,
                    typ & CloudChaser.NET_TYPE_MASK,
                    (_CODE_SEND_RSLT if rslt else 0) | (_CODE_SEND_MESG if mesg else 0),
                    data
                )
            else:
                return struct.pack(
                    f"<HHBI{len(data)}s", addr & CloudChaser.NET_ADDR_MASK,
                    port & CloudChaser.NET_PORT_MASK,
                    typ & CloudChaser.NET_TYPE_MASK,
                    wait & 0xFFFFFFFF, data
                )

        self.add(
            name='send_nowait',
            code=CODE_ID_SEND,
            encode=lambda addr, port, typ, data, mesg=False: encode_send(addr, port, typ, data, mesg, rslt=False),
        )

        self.add(
            name='send_wait',
            code=CODE_ID_SEND,
            encode=lambda addr, port, typ, data, mesg=False: encode_send(addr, port, typ, data, mesg, rslt=True),
            decode=lambda data: struct.unpack("<H", data)[0],
            response=CODE_ID_SEND_DONE
        )

        self.io.send = lambda addr, port, typ, data, mesg=False, wait=False: \
            self.io.send_nowait(addr, port, typ, data, mesg) if not wait else \
            self.io.send_wait(addr, port, typ, data, mesg)

        self.io.mesg = lambda addr, port, typ, data, wait=True: \
            self.io.send(addr, port, typ, data, mesg=True, wait=wait)

        self.add(
            name='resp',
            code=CODE_ID_RESP,
            encode=lambda addr, port, typ, data, mesg=True: encode_send(addr, port, typ, data, mesg)
        )

        self.add(
            name='recv',
            response=CODE_ID_RECV,
            decode=lambda data: struct.unpack(f"<HHHB{len(data) - 7}s", data),
            handle=self.handle_recv
        )

        def decode_trxn_stat(data):
            addr, port, typ, data = struct.unpack(f"<HHB{len(data) - 5}s", data)
            self.__update_stats_recv(len(data))
            # TODO: Validate/match port & type?
            return None if not addr else (addr, data)

        self.add(
            name='trxn',
            code=CODE_ID_TRXN,
            encode=lambda addr, port, typ, wait, data: encode_send(addr, port, typ, data, mesg=None, wait=wait),
            decode=decode_trxn_stat,
            response=CODE_ID_TRXN,
            multi=True
        )

        self.add(
            name='mac_recv',
            response=CODE_ID_MAC_RECV,
            decode=lambda data: struct.unpack(f"<HHHHbB{len(data) - 10}s", data),
            handle=self.handle_mac_recv
        )

        self.add(
            name='mac_send',
            code=CODE_ID_MAC_SEND,
            encode=lambda typ, dest, data, addr=0: struct.pack(
                f"<BBHHH{len(data)}s", typ & 0xFF, ~_CODE_MAC_SEND_WAIT & 0xFF,
                addr & 0xFFFF, dest & 0xFFFF, len(data), data
            )
        )

        self.add(
            name='mac_send_wait',
            code=CODE_ID_MAC_SEND,
            encode=lambda typ, dest, data, flag=0, addr=0: struct.pack(
                f"<BBHHH{len(data)}s", typ & 0xFF, _CODE_MAC_SEND_WAIT & 0xFF,
                addr & 0xFFFF, dest & 0xFFFF, len(data), data
            ),
            decode=lambda data: struct.unpack("<HI", data)[1],
            response=CODE_ID_MAC_SEND
        )

        def decode_peer(data):
            addr, now, data = struct.unpack(f"<HI{len(data) - 6}s", data)

            peers = []

            while len(data) >= 10:
                addri, peer, last, rssi, lqi, data = struct.unpack(f"<HHIbB{len(data) - 10}s", data)
                # TODO: This is a good place for collections.namedtuple?
                peers.append(adict(node=addri, peer=peer, last=last, rssi=rssi, lqi=lqi))

            return adict(node=addr, time=now, peers=peers)

        self.add(
            name='peer',
            code=CODE_ID_PEER,
            decode=decode_peer,
            response=CODE_ID_PEER
        )

        def decode_evnt(data):
            event, data = struct.unpack(f"<B{len(data) - 1}s", data)

            evnt = adict(id=event, data=data)

            if event == CloudChaser.NET_EVNT_PEER:
                evnt.addr, evnt.action = struct.unpack("<HB", data)

            return evnt

        self.add(
            name='evnt',
            response=CODE_ID_EVNT,
            decode=decode_evnt,
            handle=self.handle_evnt
        )

        self.add(
            name='uart',
            code=CODE_ID_UART,
            encode=lambda data: data,
            decode=lambda data: data,
            response=CODE_ID_UART,
            handle=self.handle_uart
        )

        self.add(
            name='rainbow',
            code=CODE_ID_RAINBOW,
            encode=lambda addr=CloudChaser.NET_ADDR_INVL: struct.pack("<H", addr & CloudChaser.NET_ADDR_MASK)
        )

        self.add(
            name='updt',
            code=CODE_ID_FLASH,
            encode=lambda size_header, size_user, size_code, size_text, size_data, bin_data:
                struct.pack(f"<IIIII{len(bin_data)}s", size_header, size_user, size_code, size_text, size_data, bin_data),
            decode=lambda data: struct.unpack("<i", data)[0],
            response=CODE_ID_FLASH_STAT
        )

        self.add(
            name='led',
            code=CODE_ID_LED,
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
        stat_date = datetime.fromtimestamp(stat.date).astimezone().strftime('%Y-%m-%d-%H:%M')
        return "Cloud Chaser {:08x} {} {:016X}@{:02X}:{:04X} up={}s rx={}/{}/{} tx={}/{}/{}".format(
            stat.version, stat_date, stat.serial, stat.cell, stat.addr, stat.uptime // 1000,
            stat.net_stat.recv.count, stat.net_stat.recv.size, stat.net_stat.recv.error,
            stat.net_stat.send.count, stat.net_stat.send.size, stat.net_stat.send.error
        )

    def __update_stats_recv(self, size, rssi=0, lqi=0):
        if self.stats is not None:
            self.stats.lock()
            if not self.stats.recv_count:
                self.stats.recv_time = time.time()

            self.stats.recv_size += size
            self.stats.recv_count += 1
            self.stats.rssi_sum += rssi
            self.stats.lqi_sum += lqi
            self.stats.unlock()

    def handle_mac_recv(self, mesg):
        addr, peer, dest, size, rssi, lqi, data = mesg

        self.__update_stats_recv(len(data), rssi, lqi)

        for mac_handler in self.mac_handlers:
            mac_handler(addr, peer, dest, rssi, lqi, data)

    def handle_recv(self, mesg):
        addr, dest, port, typ, data = mesg

        self.__update_stats_recv(len(data))

        for handler in self.handlers:
            handler(addr, dest, port, typ, data)

    def handle_evnt(self, evnt):
        for evnt_handler in self.evnt_handlers:
            evnt_handler(evnt)

    def handle_uart(self, data):
        for uart_handler in self.uart_handlers:
            uart_handler(data)
