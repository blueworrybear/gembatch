import unittest
from gembatch import core


def test(): ...


class TestCore(unittest.TestCase):
    def test_core(self):
        core.submit(None, lambda: 1, {})
        assert False
