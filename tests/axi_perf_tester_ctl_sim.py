from math import ceil

from hwtAxiPerfTester.runtime.axi_perf_tester_ctl import AxiPerfTesterCtl
from hwtLib.amba.constants import RESP_OKAY
from hwtLib.tools.debug_bus_monitor_ctl import words_to_int
from pyMathBitPrecise.bit_utils import ValidityError, mask


class AxiPerfTesterCtlSim(AxiPerfTesterCtl):

    def __init__(self, tc):
        AxiPerfTesterCtl.__init__(self, 0, pooling_interval=0.1)
        self.tc = tc

    def read(self, addr: int, size: int):
        axi = self.tc.u.cfg
        word_size = axi.DATA_WIDTH // 8
        words = []
        for _ in range(ceil(size / word_size)):
            assert not self.tc.sim_done
            ar_req = axi.ar._ag.create_addr_req(addr)
            axi.ar._ag.data.append(ar_req)

            r_data = axi.r._ag.data
            while not r_data:
                assert not self.tc.sim_done
                self.tc.r_data_available.acquire()

            d = r_data.popleft()[0]
            try:
                d = int(d)
            except ValidityError:
                d = d.val & d.vld_mask

            words.append(d)
            addr += word_size

        return words_to_int(words, word_size, size).to_bytes(size, "little")

    def write(self, addr:int, size:int, data:int):
        axi = self.tc.u.cfg
        word_size = axi.DATA_WIDTH // 8
        word_mask = mask(axi.DATA_WIDTH)
        word_strb = mask(word_size)
        for _ in range(ceil(size / word_size)):
            assert not self.tc.sim_done
            aw_req = axi.ar._ag.create_addr_req(addr)
            axi.aw._ag.data.append(aw_req)
            axi.w._ag.data.append((data & word_mask, word_strb))

            b_data = axi.b._ag.data
            while not b_data:
                assert not self.tc.sim_done
                self.tc.b_data_available.acquire()

            d = b_data.popleft()[0]
            assert int(d) == RESP_OKAY, d

            addr += word_size
            data >>= axi.DATA_WIDTH
