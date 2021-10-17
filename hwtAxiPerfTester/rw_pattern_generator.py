#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from hwt.code import Switch, If, Concat
from hwt.hdl.types.bits import Bits
from hwt.hdl.types.defs import BIT
from hwt.hdl.types.struct import HStruct
from hwt.interfaces.std import RegCntrl, BramPort_withoutClk, \
    Signal, Handshaked
from hwt.interfaces.utils import propagateClkRstn, addClkRstn
from hwt.math import log2ceil
from hwt.synthesizer.param import Param
from hwt.synthesizer.rtlLevel.rtlSyncSignal import RtlSyncSignal
from hwt.synthesizer.unit import Unit
from hwtLib.handshaked.builder import HsBuilder
from hwtLib.handshaked.ramAsHs import RamAsHs
from hwtLib.handshaked.streamNode import StreamNode
from hwtLib.mem.ram import RamSingleClock
from hwtLib.types.ctypes import uint16_t
from pyMathBitPrecise.bit_utils import mask


class RWPatternGenerator(Unit):
    """
    This component is based on several RAMs which can be read synchronusly or independendently for each channel.
    Each word in ram corresponds to action for this channel. By populating of this RAM any R/W pattern of constrained period
    can be generated.

    .. figure:: ./_static/RWPatternGenerator.png

    .. hwt-autodoc::
    """

    class MODE:
        SYNC = 0
        INDEPENDENT = 1

    def _config(self):
        self.ITEMS = Param(1024)
        self.COUNTER_WIDTH = Param(32)
        self.ADDR_WIDTH = Param(32)
        self.MAX_BLOCK_DATA_WIDTH = Param(None)

    def _declr(self):
        addClkRstn(self)
        self.en = RegCntrl()
        self.en.DATA_WIDTH = 1
        self.mode = Signal()

        self.en_ram_item_t = HStruct(
            (Bits(32), "addr"),  # optional address for transaction (could be used by address generator)
            (uint16_t, "delay"),  # how many cycles to wait after this transaction on this channel
            (BIT, "en"),  # flag which marks if this item is valid or if it should be skipped
            (Bits(7), None),
        )
        self.r_pattern = BramPort_withoutClk()
        self.w_pattern = BramPort_withoutClk()
        for p in [self.r_pattern, self.w_pattern]:
            p.ADDR_WIDTH = log2ceil(self.ITEMS - 1) + 1  # 2 words per item
            p.DATA_WIDTH = 32

        self.r_credit = RegCntrl()
        self.w_credit = RegCntrl()
        for c in [self.r_credit, self.w_credit]:
            c.DATA_WIDTH = self.COUNTER_WIDTH

        self.r_en = Handshaked()._m()
        self.w_en = Handshaked()._m()
        for i in [self.r_en, self.w_en]:
            i.DATA_WIDTH = self.ADDR_WIDTH

    def _construct_pattern_ram(self, cntr: RtlSyncSignal, name:str, en_reg, en_out: Handshaked):
        ram = RamSingleClock()
        ram.MAX_BLOCK_DATA_WIDTH = self.MAX_BLOCK_DATA_WIDTH
        ram.HAS_BE = True
        ram.ADDR_WIDTH = log2ceil(self.ITEMS - 1)
        assert self.ADDR_WIDTH <= self.en_ram_item_t.field_by_name["addr"].dtype.bit_length()
        ram.DATA_WIDTH = self.en_ram_item_t.bit_length()
        setattr(self, f"{name:s}_ram", ram)

        hs = RamAsHs()
        hs._updateParamsFrom(ram)
        hs.HAS_W = False
        setattr(self, f"{name:s}_hs", hs)
        hs.r.addr.data(cntr[hs.r.addr.data._dtype.bit_length():])

        conn = ram.port[0](hs.ram, exclude=[ram.port[0].we, ram.port[0].din])

        en = HsBuilder(self, hs.r.data).buff(1, (1, 2)).end
        en_data = en.data._reinterpret_cast(self.en_ram_item_t)
        stall_cntr = self._reg(f"{name:s}_stall_cntr",
                               self.en_ram_item_t.field_by_name["delay"].dtype,
                               def_val=0)
        sync = StreamNode(
            [en, ], [en_out],
            skipWhen={en_out: en.vld & ~en_data.en & en_reg}
        )
        sync.sync(stall_cntr._eq(0))
        en_out.data(en_data.addr)

        If(stall_cntr._eq(0) & sync.ack(),
           stall_cntr(en_data.delay),
        ).Elif(stall_cntr != 0,
           stall_cntr(stall_cntr - 1)
        )

        return ram, hs, conn

    def _drive_ram_port(self, master_port: BramPort_withoutClk, ram_port: BramPort_withoutClk):
        word_sel_delayed = self._reg(f"{master_port._name}_word_sel_delayed")
        word_sel_delayed(master_port.addr[0])
        return [
            ram_port.en(master_port.en),
            ram_port.addr(master_port.addr[:1]),
            If(master_port.we,
                If(~master_port.addr[0],
                    ram_port.we(mask(4))
                ).Else(
                    ram_port.we(mask(3) << 4)
                ),
            ).Else(
                ram_port.we(0),
            ),
            ram_port.din(Concat(master_port.din, master_port.din), fit=True),
            If(~word_sel_delayed,
               master_port.dout(ram_port.dout[32:]),
            ).Else(
               master_port.dout(ram_port.dout[:32], fit=True),
            )
        ]
        ram_port(master_port, fit=True),

    def _impl(self):
        en = self._reg("en", def_val=0)
        self.en.din(en)

        # how many transactions left to send
        cntr_t = Bits(self.COUNTER_WIDTH)
        credit_r = self._reg("credit_r", cntr_t)
        credit_w = self._reg("credit_w", cntr_t)
        self.r_credit.din(credit_r)
        self.w_credit.din(credit_w)

        r_pattern, r_hs, r_ram_conn = self._construct_pattern_ram(credit_r, "r", en, self.r_en)
        w_pattern, w_hs, w_ram_conn = self._construct_pattern_ram(credit_w, "w", en, self.w_en)

        sync = StreamNode([], [r_hs.r.addr, w_hs.r.addr])
        sync_r = StreamNode([], [r_hs.r.addr])
        sync_w = StreamNode([], [w_hs.r.addr])

        If(en,
            *r_ram_conn,
            *w_ram_conn,
            If(self.en.dout.vld & ~self.en.dout.data,
                # premature exit
                en(0),
                r_hs.r.addr.vld(0),
                w_hs.r.addr.vld(0),
            ).Else(
                # regular counting while credit available
                Switch(self.mode)\
                .Case(self.MODE.SYNC,
                    sync.sync(),
                    If(sync.ack(),
                       en(credit_r != 1),
                       credit_r(credit_r - 1),
                       credit_w(credit_w - 1),
                    ),
                ).Case(self.MODE.INDEPENDENT,
                    # run independently but stop when first finishes
                    sync_r.sync(),
                    sync_w.sync(),
                    If(sync.ack(),
                       en((credit_r != 1) & (credit_w != 1)),
                       credit_r(credit_r - 1),
                       credit_w(credit_w - 1),
                    ).Elif((credit_r != 1) & sync_r.ack(),
                       en(credit_r != 1),
                       credit_r(credit_r - 1),
                    ).Elif((credit_w != 1) & sync_w.ack(),
                       en(credit_w != 1),
                       credit_w(credit_w - 1),
                    ),
                ).Default(
                    r_hs.r.addr.vld(0),
                    w_hs.r.addr.vld(0),
                )
            ),
            r_pattern.port[0].din(None),
            w_pattern.port[0].din(None),
            r_pattern.port[0].we(0),
            w_pattern.port[0].we(0),
            self.r_pattern.dout(None),
            self.w_pattern.dout(None),
        ).Else(
            r_hs.r.addr.vld(0),
            w_hs.r.addr.vld(0),
            r_hs.ram.dout(None),
            w_hs.ram.dout(None),
            self._drive_ram_port(self.r_pattern, r_pattern.port[0]),
            self._drive_ram_port(self.w_pattern, w_pattern.port[0]),
            If(self.en.dout.vld,
               en(self.en.dout.data)
            ),
            If(self.r_credit.dout.vld,
               credit_r(self.r_credit.dout.data)
            ),
            If(self.w_credit.dout.vld,
               credit_w(self.w_credit.dout.data)
            ),
        )

        propagateClkRstn(self)


if __name__ == "__main__":
    from hwt.synthesizer.utils import to_rtl_str
    u = RWPatternGenerator()
    print(to_rtl_str(u))
