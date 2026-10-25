import shutil
import tempfile


def run():
    with tempfile.TemporaryDirectory() as work:
        scratch = work + "/out.txt"
        with open(scratch, "w", encoding="utf-8") as handle:
            handle.write("done")
    shutil.rmtree(work, ignore_errors=True)
    return True
