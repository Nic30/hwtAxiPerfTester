
from math import ceil
import subprocess

from hwtAxiPerfTester.runtime.axi_perf_tester_ctl import AxiPerfTesterCtl
from hwtLib.tools.debug_bus_monitor_ctl import words_to_int
from pyMathBitPrecise.bit_utils import mask


class AxiPerfTesterCtlDevmem(AxiPerfTesterCtl):

    def __init__(self, addr: int, pooling_interval=0.1):
        AxiPerfTesterCtl.__init__(self, addr, pooling_interval=pooling_interval)
        self.devmem = "devmem"
        self.word_size = 0x4

    def read(self, addr: int, size: int) -> bytes:
        addr += self.addr
        word_size = self.word_size
        words = []
        for _ in range(ceil(size / word_size)):
            s = subprocess.check_output([self.devmem, f"0x{addr:x}"])
            s = s.decode("utf-8")
            d = int(s.strip(), 16)
            words.append(d)
            addr += word_size

        return words_to_int(words, word_size, size).to_bytes(size, "little")

    def write(self, addr:int, size:int, data:int):
        addr += self.addr
        word_size = self.word_size
        word_mask = mask(word_size * 8)
        if size % word_size != 0:
            raise NotImplementedError()

        for _ in range(ceil(size / word_size)):
            d = data & word_mask
            subprocess.check_output([self.devmem, f"0x{addr:x}", 'w', f"0x{d:x}"])

            addr += word_size
            data >>= word_size * 8
