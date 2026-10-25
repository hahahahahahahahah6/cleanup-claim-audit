import os


def test_cleanup():
    os.unlink("/tmp/scratch")
