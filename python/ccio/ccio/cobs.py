"""Consistent Overhead Byte Stuffing

https://github.com/Jeff-Ciesielski/pycobs/blob/master/cobs.py

Copyright 2013, Jeff Ciesielski <jeffciesielski@gmail.com>
Redistribution and use in source and binary forms are permitted,
with or without modification.

This is based on the C implementation of COBS by Jacques Fortier.
"""


def cobs_encode(data):
    """COBS-Encode bytes.

    :param data: input bytes
    :return: cobs-encoded bytearray
    """
    read_index = 0
    write_index = 1
    code_index = 0
    code = 1
    output = bytearray(len(data) + 1 + (len(data) // 254))

    while read_index < len(data):
        if not data[read_index]:
            output[code_index] = code
            code = 1
            code_index = write_index
            write_index += 1
            read_index += 1

        else:
            output[write_index] = data[read_index]
            read_index += 1
            write_index += 1
            code += 1

            if code == 0xff:
                output[code_index] = code
                code = 1
                code_index = write_index
                write_index += 1

    output[code_index] = code

    return output[:write_index]


def cobs_decode(data):
    """Decode a byte array.
    :param data: input bytes
    :return: length, decoded
    """
    read_index = 0
    write_index = 0
    code = 0
    output = bytearray(len(data))

    while read_index < len(data):
        code = data[read_index]
        if (read_index + code) > len(data) and code != 1:
            return b''

        read_index += 1

        for i in range(code - 1):
            output[write_index] = data[read_index]
            write_index += 1
            read_index += 1

        if code != 0xff and read_index != len(data):
            output[write_index] = 0
            write_index += 1

    return output[:write_index]
