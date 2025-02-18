"""Asynchronous queue.
"""
import threading


class AsyncQ:
    __prod = None
    __sync = None
    __q = None

    def __init__(self, size=None):
        self.__sync = threading.Semaphore(0)
        self.__q = []

        if size:
            self.__prod = threading.Semaphore(size)
            self.send = self.__send_prod
        else:
            self.send = self.__send

    def push(self, item, timeout=0):
        """Push an item onto the end, removing oldest if needed.
        :param item: Item to queue.
        :param timeout: Time to wait, cannot be None.
        :return: Success of the send after pop.
        """
        assert timeout is not None
        if not self.send(item, timeout=timeout):
            tuple(self.recv(once=True, timeout=0))
            return self.send(item, timeout=0)
        return True

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

            if self.__prod is not None:
                self.__prod.release()

            yield evnt

            if once:
                break

    def __send(self, item):
        self.__q.append(item)
        self.__sync.release()
        return True

    def __send_prod(self, item, timeout=None):
        if self.__prod.acquire(timeout=timeout):
            return self.__send(item)
        return False

    def send(self, item):
        """Send an item to the back of the queue.
        """
        raise NotImplementedError
