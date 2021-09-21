
from math import ceil
import subprocess

from hwtAxiPerfTester.runtime.axi_perf_tester_ctl import AxiPerfTesterCtl
from hwtLib.tools.debug_bus_monitor_ctl import words_to_int
from pyMathBitPrecise.bit_utils import mask


class AxiPerfTesterCtlDevmem(AxiPerfTesterCtl):

    def __init__(self, addr):
        AxiPerfTesterCtl.__init__(self, addr)
        self.devmem = "devmem"

    def read(self, addr: int, size: int) -> bytes:
        addr += self.addr
        word_size = 0x4
        words = []
        for _ in range(ceil(size / word_size)):
            s = subprocess.check_output([self.devmem, f"0x{addr:x}"])
            s = s.decode("utf-8")
            d = int(s.strip(), 16)
            words.append(d)
            addr += word_size

        return words_to_int(words, word_size, size).to_bytes(size, "little")

    def write(self, addr:int, size:int, data:int):
        axi = self.tc.u.cfg
        word_size = axi.DATA_WIDTH // 8
        word_mask = mask(axi.DATA_WIDTH)
        word_strb = mask(word_size)
        if size % word_size != 0:
            raise NotImplementedError()

        for _ in range(ceil(size / word_size)):
            assert not self.tc.sim_done
            d = data & word_mask
            subprocess.check_output([self.devmem, f"0x{addr:x}", 'w', f"0x{d:x}"])
            axi.w._ag.data.append((data & word_mask, word_strb))

            addr += word_size
            data >>= axi.DATA_WIDTH
