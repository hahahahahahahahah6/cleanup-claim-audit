import os


def run(path):
    os.unlink(path)
    return True
