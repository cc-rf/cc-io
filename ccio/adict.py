"""Attribute dictionary.

Access keys as if they were fields (because they are).
"""
from collections import OrderedDict


class adict(dict):
    def __init__(self, *args, **kwargs):
        super(adict, self).__init__(*args, **kwargs)
        self.__dict__ = self


class oadict(OrderedDict):
    def __init__(self, *args, **kwargs):
        super(oadict, self).__init__(*args, **kwargs)
        self.__dict__ = self
