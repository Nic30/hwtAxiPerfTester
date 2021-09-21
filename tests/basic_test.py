#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from collections import deque
import threading
import unittest

from hwt.simulator.simTestCase import SimTestCase
from hwtAxiPerfTester.address_generator import AddressGenerator
from hwtAxiPerfTester.axi_perf_tester import AxiPerfTester
from hwtAxiPerfTester.runtime.data_containers import \
    AxiPerfTesterTestJob, AxiPerfTesterChannelConfig, AxiPerfTesterStatConfig, \
    AxiPerfTesterTestReport
from hwtAxiPerfTester.rw_pattern_generator import RWPatternGenerator
from hwtAxiPerfTester.time_duration_storage import TimeDurationStorage
from hwtLib.amba.axi_comp.sim.ram import AxiSimRam
from hwtSimApi.constants import CLK_PERIOD
from hwtSimApi.triggers import Timer, StopSimumulation
from tests.axi_perf_tester_ctl_sim import AxiPerfTesterCtlSim
from hwtLib.amba.axiLite_comp.sim.utils import axi_randomize_per_channel


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
        #axi_randomize_per_channel(self, u.cfg)
        axi_randomize_per_channel(self, u.axi)

        def time_sync():
            while True:
                if u.cfg.r._ag.data and self.r_data_available.locked():
                    tc.r_data_available.release()
                yield Timer(CLK_PERIOD)
                if self.sim_done:
                    raise StopSimumulation()

        mem = self.mem
        for i in range(0x1000 // (u.DATA_WIDTH // 8)):
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
            ag.addr_mask = 0x1000 - 1
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

        #import json
        #with open("example_data.json", "w") as f:
        #    json.dump(rep.to_json(), f, indent=2, separators=(',', ': '))

        for ch_i, ch in enumerate(rep.channel):
            self.assertEqual(ch.credit, 0, ch_i)
            self.assertEqual(ch.dispatched_cntr, 10, ch_i)
            self.assertEqual(sum(ch.histogram_counters), 10, ch_i)
            self.assertEqual(sum(1 if c > 0 else 0 for c in ch.last_values), min(u.LAST_VALUES_ITEMS, 10), ch_i)
            self.assertGreater(ch.min_val, 0, ch_i)
            self.assertGreaterEqual(ch.max_val, ch.min_val, ch_i)
            self.assertGreater(ch.sum_val, 10, ch_i)
            self.assertEqual(ch.input_cnt, 10, ch_i)
            self.assertGreater(ch.last_time, 10, ch_i)
            self.assertLessEqual(ch.last_time, rep.time, ch_i)


if __name__ == "__main__":
    suite = unittest.TestSuite()
    # suite.addTest(DebugBusMonitorExampleAxiTC('test_write'))
    suite.addTest(unittest.makeSuite(AxiPerfTesterTC))
    runner = unittest.TextTestRunner(verbosity=3)
    runner.run(suite)
