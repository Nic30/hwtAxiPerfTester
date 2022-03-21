# hwtAxiPerfTester

[![CircleCI](https://circleci.com/gh/Nic30/hwtAxiPerfTester.svg?style=svg)](https://circleci.com/gh/Nic30/hwtAxiPerfTester)
[![Coverage Status](https://coveralls.io/repos/github/Nic30/hwtAxiPerfTester/badge.svg?branch=master)](https://coveralls.io/github/Nic30/hwtAxiPerfTester?branch=master)
[![PyPI version](https://badge.fury.io/py/hwtAxiPerfTester.svg)](http://badge.fury.io/py/hwtAxiPerfTester)
[![Documentation Status](https://readthedocs.org/projects/hwtAxiPerfTester/badge/?version=latest)](http://hwtAxiPerfTester.readthedocs.io/en/latest/?badge=latest)

This repository contains a hardware AXI4/3 tester which can be exported to System Verilog/VHDL/SystemC and its control application.
It was originally used on Xilinx Virtex Ultrascale+ and Intel Arria10 to test properties of DDR4 controllers for various access patterns.
But it does not contain any vendor specifics and should run everywhere.

The top component of tester is hwtAxiPerfTester.axi_perf_tester.AxiPerfTester to see it in default configuration just download or install this repo and run
`python3 -m hwtAxiPerfTester.axi_perf_tester`.

The tests are cosimulation, you can modify config in tests and see what it does.

## Installation and usage

```
pip3 install --upgrade --no-cache\
    -r https://raw.githubusercontent.com/Nic30/hwtAxiPerfTester/master/doc/requirements.txt \
    git+https://github.com/Nic30/hwtAxiPerfTester#egg=hwtAxiPerfTester
```

Once you have a design you can start script the tests scenarios.


```Python

from hwtAxiPerfTester.runtime.data_containers import \
    AxiPerfTesterTestJob, AxiPerfTesterChannelConfig, AxiPerfTesterStatConfig, \
    AxiPerfTesterTestReport
from hwtAxiPerfTester.runtime.axi_perf_tester_ctl_devmem import AxiPerfTesterCtlDevmem
from hwtAxiPerfTester.rw_pattern_generator import RWPatternGenerator
from hwtAxiPerfTester.transaction_generator import TransactionGenerator
from hwtAxiPerfTester.time_duration_storage import TimeDurationStorage

job = AxiPerfTesterTestJob()
job.rw_mode = RWPatternGenerator.MODE.SYNC
for ch in job.channel_config:
    ch: AxiPerfTesterChannelConfig
    ch.pattern = [1 for _ in range(4)]
    ag = ch.addr_gen
    ag.ordering_mode = TimeDurationStorage.MODE.IN_ORDER
    ag.credit = 10
    ag.addr = 0
    ag.addr_step = 64
    ag.addr_mask = 0x1000 - 1
    ag.addr_mode = TransactionGenerator.MODE.MODULO
    ag.addr_offset = 0x0
    ag.trans_len = 0
    ag.trans_len_step = 0
    ag.trans_len_mask = 1
    ag.trans_len_mode = TransactionGenerator.MODE.MODULO

    st = ch.stat_config
    st: AxiPerfTesterStatConfig
    st.histogram_keys = [2, 4, 8]

db = AxiPerfTesterCtlDevmem(0x02000000)
rep = db.exec_test(job)

print("Output:")
print(rep.to_json())
```
