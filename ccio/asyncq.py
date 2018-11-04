"""Asynchronous queue.
"""
import threading


class AsyncQ:
    __sync = None
    __q = None

    def __init__(self):
        self.__sync = threading.Semaphore(0)
        self.__q = []

    def recv(self, once=False, timeout=None):
        """Receive a queued item.
        :param once: Stop iterating after first item.
        :param timeout: Timeout in seconds or None.
        :return: Iterater of queue items.
        """
        while 1:
            if not self.__sync.acquire(timeout=timeout):
                break

            evnt = self.__q.pop(0)

            yield evnt

            if once:
                break

    def send(self, item):
        """Send an item to the back of the queue.
        """
        self.__q.append(item)
        self.__sync.release()
