from typing import Tuple, List

from hwtAxiPerfTester.transaction_generator import TransactionGenerator
from hwtAxiPerfTester.rw_pattern_generator import RWPatternGenerator
from hwtAxiPerfTester.time_duration_storage import TimeDurationStorage


class PrimitiveJsonObject():

    def to_json(self):
        return self.__dict__

    @classmethod
    def from_json(cls, d):
        self = cls()
        for k, v in d.items():
            setattr(self, k, v)
        return self


class AxiPerfTesterAddrGenConfig():
    """
    :ivar credit: number of transactin attempts (real number depends on rw pattern)
    :ivar addr: starting address
    :ivar addr_step: addr step for modulo mode
    :ivar addr_mask: final mask of address
    :ivar addr_mode: :see: :class:`AddressGenerator.MODE`
    :ivar addr_offset: final offset of address
    :ivar trans_len: starting length of transaction (0 = 1 word, 1=2words, ...)

    """

    def __init__(self):
        self.ordering_mode = TimeDurationStorage.MODE.IN_ORDER
        self.credit = 1000
        self.addr = 0
        self.addr_step = 64
        self.addr_mask = 0x1000 - 1
        self.addr_mode = TransactionGenerator.MODE.MODULO
        self.addr_offset = 0x0
        self.trans_len = 0
        self.trans_len_step = 0
        self.trans_len_mask = 1
        self.trans_len_mode = TransactionGenerator.MODE.MODULO


class AxiPerfTesterChannelConfig():

    def __init__(self):
        self.pattern: List[bool] = []
        self.addr_gen = AxiPerfTesterAddrGenConfig()
        self.stat_config = AxiPerfTesterStatConfig()


class AxiPerfTesterStatConfig():

    def __init__(self):
        self.histogram_keys:List[int] = []


class AxiPerfTesterTestJob():

    def __init__(self):
        self.rw_mode = RWPatternGenerator.MODE.SYNC
        self.channel_config: Tuple[AxiPerfTesterChannelConfig, AxiPerfTesterChannelConfig] = (
            AxiPerfTesterChannelConfig(),
            AxiPerfTesterChannelConfig(),
        )


class AxiPerfTesterTestReport():

    def __init__(self):
        self.time = 0
        self.channel: Tuple[AxiPerfTesterTestChannelReport, AxiPerfTesterTestChannelReport] = (
            AxiPerfTesterTestChannelReport(), AxiPerfTesterTestChannelReport()
        )

    def to_json(self):
        return {
            "time": self.time,
            "channel": [d.to_json() for d in self.channel],
        }

    @classmethod
    def from_dict(cls, d):
        self = cls()
        self.time = d["time"]
        self.channel = tuple(AxiPerfTesterTestChannelReport.from_json(_d) for _d in d["channel"]),
        return self


class AxiPerfTesterTestChannelReport(PrimitiveJsonObject):
    """
    :ivar credit: number of not processed transactions (remaining job or possition where job was interrupted by finish of other channel)
    :ivar dispatched_cntr: number of dispatched transactions which need sto be collected from system before rurning off
    :ivar histogram_counters: values of histogram
    :ivar last_values: n last values (cyclyc buffer, last item is on position input_cnt % last_values_items)
    :ivar last_time: time of last data arrival, used to determine total duration of batch
    """

    def __init__(self):
        self.credit = 0
        self.dispatched_cntr = 0
        self.histogram_counters: List[int] = []
        self.histogram_keys: List[int] = []
        self.last_values: List[int] = []
        self.min_val = 0
        self.max_val = 0
        self.sum_val = 0
        self.input_cnt = 0
        self.last_time = 0


if __name__ == "__main__":
    o = AxiPerfTesterTestReport()
    j = o.to_json()
    o2 = AxiPerfTesterTestReport.from_dict(j)
    print(o2)
