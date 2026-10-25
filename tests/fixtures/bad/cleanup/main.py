import os
import tempfile


def run():
    fd, path = tempfile.mkstemp()
    os.write(fd, b"done")
    os.close(fd)
    return path
