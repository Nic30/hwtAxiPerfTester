from hwt.code import Switch, If
from hwt.hdl.types.bits import Bits
from hwt.interfaces.std import RegCntrl, BramPort_withoutClk, HandshakeSync, \
    Signal
from hwt.interfaces.utils import propagateClkRstn, addClkRstn
from hwt.math import log2ceil
from hwt.synthesizer.param import Param
from hwt.synthesizer.rtlLevel.rtlSyncSignal import RtlSyncSignal
from hwt.synthesizer.unit import Unit
from hwtLib.handshaked.builder import HsBuilder
from hwtLib.handshaked.ramAsHs import RamAsHs
from hwtLib.handshaked.streamNode import StreamNode
from hwtLib.mem.ram import RamSingleClock


class RWPatternGenerator(Unit):

    class MODE:
        SYNC = 0
        INDEPENDENT = 1

    def _config(self):
        self.ITEMS = Param(1024)
        self.COUNTER_WIDTH = Param(32)

    def _declr(self):
        addClkRstn(self)
        self.en = RegCntrl()
        self.en.DATA_WIDTH = 1
        self.mode = Signal()

        self.r_pattern = BramPort_withoutClk()
        self.w_pattern = BramPort_withoutClk()
        for p in [self.r_pattern, self.w_pattern]:
            p.ADDR_WIDTH = log2ceil(self.ITEMS - 1)
            p.DATA_WIDTH = 1

        self.r_credit = RegCntrl()
        self.w_credit = RegCntrl()
        for c in [self.r_credit, self.w_credit]:
            c.DATA_WIDTH = self.COUNTER_WIDTH

        self.r_en = HandshakeSync()._m()
        self.w_en = HandshakeSync()._m()

    def _construct_pattern_ram(self, cntr: RtlSyncSignal, name:str, en_reg, en_out: HandshakeSync):
        ram = RamSingleClock()
        ram.ADDR_WIDTH = log2ceil(self.ITEMS - 1)
        ram.DATA_WIDTH = 1
        setattr(self, f"{name:s}_ram", ram)

        hs = RamAsHs()
        hs._updateParamsFrom(ram)
        hs.HAS_W = False
        setattr(self, f"{name:s}_hs", hs)
        hs.r.addr.data(cntr[hs.r.addr.data._dtype.bit_length():])

        conn = ram.port[0](hs.ram, exclude=[ram.port[0].we, ram.port[0].din])

        en = HsBuilder(self, hs.r.data).buff(1, (1, 2)).end
        StreamNode(
            [en, ], [en_out],
            skipWhen={en_out: en.vld & ~en.data & en_reg}
        ).sync()

        return ram, hs, conn

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
                       en(credit_r != 0),
                       credit_r(credit_r - 1),
                       credit_w(credit_w - 1),
                    ),
                ).Case(self.MODE.INDEPENDENT,
                    # run independently but stop when first finishes
                    sync_r.sync(),
                    sync_w.sync(),
                    If(sync.ack(),
                       en((credit_r != 0) & (credit_w != 0)),
                       credit_r(credit_r - 1),
                       credit_w(credit_w - 1),
                    ).Elif((credit_r != 0) & sync_r.ack(),
                       en(credit_r != 0),
                       credit_r(credit_r - 1),
                    ).Elif((credit_w != 0) & sync_w.ack(),
                       en(credit_w != 0),
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
            r_pattern.port[0](self.r_pattern),
            w_pattern.port[0](self.w_pattern),
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
