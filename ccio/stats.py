"""Cloud Chaser Support Library
"""
import sys
import time
import threading
import traceback


class Stats:
    recv_count = 0
    recv_time = 0
    recv_size = 0
    rssi_sum = 0
    lqi_sum = 0

    _start_time = 0
    _lock = None

    file = None

    def __init__(self, file):
        self.file = file
        self._lock = threading.Lock()

    def start(self):
        self._start_time = time.time()
        self.run()

    def lock(self):
        self._lock.acquire()

    def unlock(self):
        self._lock.release()

    def run(self):
        thr = threading.Timer(5, self._run)
        thr.setDaemon(True)
        thr.start()

        if not self.recv_count:
            return

        self.lock()

        recv_count = self.recv_count
        recv_time = self.recv_time
        recv_size = self.recv_size
        rssi_sum = self.rssi_sum
        lqi_sum = self.lqi_sum

        self.recv_count = 0
        self.recv_size = 0
        self.rssi_sum = 0
        self.lqi_sum = 0

        self.unlock()

        now = time.time()

        diff = now - recv_time

        if diff:
            d_rate = round(float(recv_size) / diff)
            p_rate = round(float(recv_count) / diff)
        else:
            d_rate = 0
            p_rate = 0

        if recv_count:
            rssi_avg = round(rssi_sum / recv_count)
            lqi_avg = round(lqi_sum / recv_count)
        else:
            rssi_avg = 0
            lqi_avg = 0

        elapsed = int(round(now - self._start_time))
        elapsed -= elapsed % 5
        elapsed_hour = elapsed // 3600
        elapsed_min = (elapsed // 60) % 60
        elapsed_sec = elapsed % 60

        print(
            "{:02d}:{:02d}:{:02d}  {:5d} Bps / {:3d} pps \t rssi {:<4d}  lqi {:<2d}".format(
                elapsed_hour, elapsed_min, elapsed_sec, d_rate, p_rate, rssi_avg, lqi_avg
            ), file=self.file
        )

        # TODO: Maybe also add totals to this output ^

    def _run(self):
        try:
            self.run()

        except:
            traceback.print_exc()
            sys.exit(1)
