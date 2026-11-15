"""Keep pytest temporary files inside this checkout, independent of Windows TEMP ACLs."""

import tempfile
from pathlib import Path


def pytest_configure(config):
    # Respect an explicit --basetemp. Otherwise allocate a private directory per
    # invocation: simultaneous runs never clear each other's temporary files.
    if config.option.basetemp is not None:
        return
    parent = Path(__file__).resolve().parent / ".pytest_tmp"
    parent.mkdir(exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix="run-", dir=parent)
    config.option.basetemp = temporary.name
    config.add_cleanup(temporary.cleanup)
