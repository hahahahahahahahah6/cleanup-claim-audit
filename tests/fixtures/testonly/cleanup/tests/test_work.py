import shutil


def test_cleanup():
    shutil.rmtree("/tmp/scratch", ignore_errors=True)
