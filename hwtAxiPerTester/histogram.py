from typing import List

from hwt.code import Switch, If
from hwt.interfaces.std import BramPort_withoutClk, VldSynced
from hwt.interfaces.utils import addClkRstn
from hwt.math import log2ceil
from hwt.serializer.mode import serializeParamsUniq
from hwt.synthesizer.param import Param
from hwt.synthesizer.rtlLevel.rtlSyncSignal import RtlSyncSignal
from hwt.synthesizer.unit import Unit


@serializeParamsUniq
class HistogramDynamic(Unit):
    """
    Simple array of counters and keys wich counts inputs as histogram would

    .. hwt-autodoc::
    """

    def _config(self) -> None:
        self.ITEMS = Param(4)
        self.COUNTER_WIDTH = Param(32)
        self.VALUE_WIDTH = Param(16)

    def _declr(self) -> None:
        addClkRstn(self)
        self.data_in = VldSynced()
        self.data_in.DATA_WIDTH = self.VALUE_WIDTH
        assert self.ITEMS > 1, self.ITEMS
        k = self.keys = BramPort_withoutClk()
        c = self.counters = BramPort_withoutClk()
        k.ADDR_WIDTH = c.ADDR_WIDTH = log2ceil(self.ITEMS - 1)
        k.DATA_WIDTH = self.VALUE_WIDTH
        c.DATA_WIDTH = self.COUNTER_WIDTH

    def drive_reg_array_from_bramport(self, bram_port, reg_array):
        read_driver = \
        Switch(bram_port.addr)\
        .add_cases(
            ((i, bram_port.dout(k)) for i, k in enumerate(reg_array)),
        ).Default(
            bram_port.dout(None),
        )

        write_driver = \
        If(bram_port.en & bram_port.we,
           Switch(bram_port.addr)\
           .add_cases(
               ((i, k(bram_port.din)) for i, k in enumerate(reg_array))
           )
        )
        return read_driver, write_driver

    def _cntr_tick_expr(self, keys: List[RtlSyncSignal], i: int):
        din = self.data_in
        last = self.ITEMS - 1
        if i == 0:
            return din.vld & (din.data < keys[0])

        elif i == last:
            return din.vld & (din.data >= keys[i - 1])

        else:
            return din.vld & (din.data >= keys[i - 1]) & (din.data < keys[i])

    def _impl(self) -> None:
        key_io = self.keys
        key_t = key_io.din._dtype
        keys = [self._reg(f"key_{i:d}_{i+1:d}", key_t) for i in range(self.ITEMS - 1)]
        self.drive_reg_array_from_bramport(key_io, keys)

        c_io = self.counters
        cntr_t = c_io.din._dtype
        cntr = [self._reg(f"cntr_{i:d}", cntr_t) for i in range(self.ITEMS)]
        _, counter_write = self.drive_reg_array_from_bramport(c_io, cntr)
        counter_write.Else(
            If(self._cntr_tick_expr(keys, i),
               cntr[i](cntr[i] + 1)
            ) for i in range(self.ITEMS)
        )


if __name__ == "__main__":
    from hwt.synthesizer.utils import to_rtl_str
    u = HistogramDynamic()
    print(to_rtl_str(u))

