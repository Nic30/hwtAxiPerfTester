from hwt.code import If
from hwt.hdl.types.bits import Bits
from hwt.interfaces.std import Signal, BramPort_withoutClk, \
    Handshaked, RegCntrl
from hwt.interfaces.utils import addClkRstn, propagateClkRstn
from hwt.math import log2ceil, hMin, hMax
from hwt.serializer.mode import serializeParamsUniq
from hwt.synthesizer.hObjList import HObjList
from hwt.synthesizer.param import Param
from hwt.synthesizer.unit import Unit
from hwtAxiPerfTester.histogram import HistogramDynamic
from hwtLib.mem.ram import RamSingleClock


@serializeParamsUniq
class StatisticCollector(Unit):

    def _config(self) -> None:
        self.TRANS_ID_WIDTH:int = Param(6)
        self.COUNTER_WIDTH:int = Param(32)
        self.HISTOGRAM_ITEMS:int = Param(32)
        self.LAST_VALUES_ITEMS = Param(4096)
        self.TIME_WIDTH:int = Param(32)

    def _declr(self) -> None:
        addClkRstn(self)
        self.en = Signal()
        self.time = Signal(Bits(self.TIME_WIDTH))

        trans_stats = self.trans_stats = Handshaked()
        trans_stats.DATA_WIDTH = self.TIME_WIDTH

        k = self.histogram_keys = BramPort_withoutClk()
        c = self.histogram_counters = BramPort_withoutClk()
        k.ADDR_WIDTH = c.ADDR_WIDTH = log2ceil(self.HISTOGRAM_ITEMS - 1)
        c.DATA_WIDTH = k.DATA_WIDTH = self.COUNTER_WIDTH

        lv = self.last_values = BramPort_withoutClk()
        lv.DATA_WIDTH = self.trans_stats.DATA_WIDTH
        lv.ADDR_WIDTH = log2ceil(self.LAST_VALUES_ITEMS - 1)

        self.cntr_io = HObjList([RegCntrl() for _ in range(5)])
        for r in self.cntr_io:
            r.DATA_WIDTH = self.COUNTER_WIDTH

    def _impl(self) -> None:
        histogram = HistogramDynamic()
        histogram.VALUE_WIDTH = self.TIME_WIDTH
        histogram.COUNTER_WIDTH = self.COUNTER_WIDTH
        histogram.ITEMS = self.HISTOGRAM_ITEMS

        self.histogram = histogram
        histogram.keys(self.histogram_keys)
        histogram.counters(self.histogram_counters)

        last_values = RamSingleClock()
        last_values.PORT_CNT = 1
        last_values.DATA_WIDTH = self.trans_stats.DATA_WIDTH
        last_values.ADDR_WIDTH = log2ceil(self.LAST_VALUES_ITEMS - 1)
        self.last_values_ram = last_values

        min_val, max_val, sum_val, input_cnt, last_time = [
             self._reg(n, Bits(self.COUNTER_WIDTH))
            for n in  ["min_val", "max_val", "sum_val", "input_cnt", "last_time",  # "reorder_cnt"
                       ]]
        regs = [min_val, max_val, sum_val, input_cnt, last_time]

        stats = self.trans_stats
        stats.rd(1)
        histogram.data_in(stats, exclude=[stats.rd])
        for c_io, c in zip(self.cntr_io, regs):
            c_io.din(c),

        If(stats.vld & self.en,
           min_val(hMin(min_val, stats.data)),
           max_val(hMax(max_val, stats.data)),
           sum_val(sum_val + stats.data),
           input_cnt(input_cnt + 1),
           last_time(self.time),
           last_values.port[0].addr(input_cnt, fit=True),
           last_values.port[0].en(1),
           last_values.port[0].we(1),
           last_values.port[0].din(stats.data),
           self.last_values.dout(None),
        ).Else(
            *(
                If(c_io.dout.vld,
                   c(c_io.dout.data)
                )
                for c_io, c in zip(self.cntr_io, regs)
            ),
            last_values.port[0](self.last_values)
        )

        propagateClkRstn(self)


if __name__ == "__main__":
    from hwt.synthesizer.utils import to_rtl_str
    u = StatisticCollector()
    print(to_rtl_str(u))
