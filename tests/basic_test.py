
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from collections import deque
from math import ceil
import threading
import unittest

from hwt.simulator.simTestCase import SimTestCase
from hwtAxiPerfTester.axi_perf_tester import AxiPerfTester
from hwtAxiPerfTester.runtime.axi_perf_tester_ctl import AxiPerfTesterCtl, \
    AxiPerfTesterTestJob, AxiPerfTesterChannelConfig, AxiPerfTesterStatConfig, \
    AxiPerfTesterTestReport
from hwtLib.amba.axi_comp.sim.ram import AxiSimRam
from hwtLib.amba.constants import RESP_OKAY
from hwtLib.tools.debug_bus_monitor_ctl import words_to_int
from hwtSimApi.constants import CLK_PERIOD
from hwtSimApi.triggers import Timer, StopSimumulation
from pyMathBitPrecise.bit_utils import ValidityError, mask
from hwtAxiPerfTester.rw_pattern_generator import RWPatternGenerator
from hwtAxiPerfTester.time_duration_storage import TimeDurationStorage
from hwtAxiPerfTester.address_generator import AddressGenerator


class AxiPerfTesterCtlSim(AxiPerfTesterCtl):

    def __init__(self, tc):
        u = tc.u
        AxiPerfTesterCtl.__init__(self, 0,
                                  u.RW_PATTERN_ITEMS,
                                  u.HISTOGRAM_ITEMS, u.LAST_VALUES_ITEMS, pooling_interval=0.1
                                  )
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


def run_AxiPerfTesterCtlSim(tc, job, data):
    db = AxiPerfTesterCtlSim(tc)
    rep = db.exec_test(job)
    data.append(rep)
    tc.sim_done = True


class AxiPerfTesterTC(SimTestCase):

    @classmethod
    def setUpClass(cls):
        u = cls.u = AxiPerfTester()
        u.HISTOGRAM_ITEMS = 4
        u.LAST_VALUES_ITEMS = 4
        u.ID_WIDTH = 4
        u.RW_PATTERN_ITEMS = 4
        u.DATA_WIDTH = 32
        cls.compileSim(u)

    def setUp(self):
        SimTestCase.setUp(self)
        self.sim_done = False
        self.r_data_available = threading.Lock()
        self.r_data_available.acquire()
        self.b_data_available = threading.Lock()
        self.b_data_available.acquire()
        self.mem = AxiSimRam(self.u.axi)

    def setUpQueues(self):
        u = self.u

        class RSpyDeque(deque):

            def __init__(self, tc):
                super(RSpyDeque, self).__init__()
                self.tc = tc

            def append(self, x):
                if self.tc.r_data_available.locked():
                    self.tc.r_data_available.release()
                super(RSpyDeque, self).append(x)

        class BSpyDeque(deque):

            def __init__(self, tc):
                super(BSpyDeque, self).__init__()
                self.tc = tc

            def append(self, x):
                if self.tc.b_data_available.locked():
                    self.tc.b_data_available.release()
                super(BSpyDeque, self).append(x)

        u.cfg.r._ag.data = RSpyDeque(self)
        u.cfg.b._ag.data = BSpyDeque(self)

    def test_dump(self):
        u: AxiPerfTester = self.u
        tc = self
        self.setUpQueues()

        def time_sync():
            while True:
                if u.cfg.r._ag.data and self.r_data_available.locked():
                    tc.r_data_available.release()
                yield Timer(CLK_PERIOD)
                if self.sim_done:
                    raise StopSimumulation()

        mem = self.mem
        for i in range(0x1000 // 64):
            mem.data[i] = i

        self.procs.extend([time_sync()])
        job = AxiPerfTesterTestJob()
        job.rw_mode = RWPatternGenerator.MODE.SYNC
        for ch in job.channel_config:
            ch: AxiPerfTesterChannelConfig
            ch.pattern = [1 for _ in range(u.RW_PATTERN_ITEMS)]
            ag = ch.addr_gen
            ag.ordering_mode = TimeDurationStorage.MODE.IN_ORDER
            ag.credit = 10
            ag.addr = 0
            ag.addr_step = 64
            ag.addr_mask = 0x1000
            ag.addr_mode = AddressGenerator.MODE.MODULO
            ag.addr_offset = 0x0
            ag.trans_len = 0
            ag.trans_len_step = 0
            ag.trans_len_mask = 1
            ag.trans_len_mode = AddressGenerator.MODE.MODULO

            st = ch.stat_config
            st: AxiPerfTesterStatConfig
            st.histogram_keys = [1, 4, 8]

        reports = []
        ctl_thread = threading.Thread(target=run_AxiPerfTesterCtlSim,
                                      args=(self, job, reports))
        ctl_thread.start()
        # actually takes less time as the simulation is stopped after ctl_thread end
        self.runSim(12000 * CLK_PERIOD)
        # handle the case where something went wrong and ctl thread is still running
        self.sim_done = True
        if self.r_data_available.locked():
            self.r_data_available.release()
        ctl_thread.join()

        self.assertEqual(len(reports), 1)
        rep: AxiPerfTesterTestReport = reports[0]
        self.assertGreater(rep.time, 10)
        for ch in rep.channel:
            self.assertEqual(ch.credit, 0)
            self.assertEqual(ch.dispatched_cntr, 10)
            self.assertEqual(sum(ch.histogram_counters), 10)
            self.assertEqual(sum(1 if c > 0 else 0 for c in ch.last_values), min(u.LAST_VALUES_ITEMS, 10))
            self.assertGreater(ch.min_val, 0)
            self.assertGreaterEqual(ch.max_val, ch.min_val)
            self.assertGreater(ch.sum_val, 10)
            self.assertEqual(ch.input_cnt, 10)
            self.assertGreater(ch.last_time, 10)
            self.assertLessEqual(ch.last_time, rep.time)


if __name__ == "__main__":
    suite = unittest.TestSuite()
    # suite.addTest(DebugBusMonitorExampleAxiTC('test_write'))
    suite.addTest(unittest.makeSuite(AxiPerfTesterTC))
    runner = unittest.TextTestRunner(verbosity=3)
    runner.run(suite)
