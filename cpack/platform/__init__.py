"""Everything that differs between operating systems lives behind this one module (spec 12, D8).
Mac is the only file that works in slice 1; windows.py names what has to be written there."""
import sys


def get():
    if sys.platform.startswith('win'):
        from . import windows as p
    else:
        from . import mac as p
    return p
