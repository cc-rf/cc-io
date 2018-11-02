

def cobs_encode(data):
    """COBS-Encode bytes.
    :param data: input bytes
    :return: cobs-encoded bytearray
    """
    out = bytearray(len(data) + 1 + (len(data) // 254))
    ci = ri = 0
    c = wi = 1

    while ri < len(data):
        if not data[ri]:
            out[ci] = c
            c = 1
            ci = wi
            wi += 1
            ri += 1
        else:
            out[wi] = data[ri]
            ri += 1
            wi += 1
            c += 1
            if c == 0xFF:
                out[ci] = c
                c = 1
                ci = wi
                wi += 1
    out[ci] = c

    return out[:wi]


def cobs_decode(data):
    """Decode a byte array.
    :param data: input bytes
    :return: length, decoded
    """
    out = bytearray(len(data))
    ri = wi = 0

    while ri < len(data):
        c = data[ri]
        if (ri + c) > len(data) and c != 1:
            return bytearray()
        ri += 1
        for i in range(c - 1):
            out[wi] = data[ri]
            wi += 1
            ri += 1
        if c != 0xFF and ri != len(data):
            out[wi] = 0
            wi += 1

    return out[:wi]
