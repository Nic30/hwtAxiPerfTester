#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from hwt.code import Switch
from hwt.hdl.constants import WRITE, READ
from hwt.hdl.types.bits import Bits
from hwt.hdl.types.struct import HStruct
from hwt.interfaces.hsStructIntf import HsStructIntf
from hwt.interfaces.std import Handshaked, Signal
from hwt.interfaces.utils import addClkRstn, propagateClkRstn
from hwt.synthesizer.param import Param
from hwt.synthesizer.unit import Unit
from hwtLib.amba.axi4 import Axi4
from hwtLib.amba.axi_comp.lsu.fifo_oooread import FifoOutOfOrderRead
from hwtLib.handshaked.fifo import HandshakedFifo
from hwtLib.handshaked.ramAsHs import RamAsHs
from hwtLib.handshaked.reg import HandshakedReg
from hwtLib.handshaked.streamNode import StreamNode
from hwtLib.mem.ram import RamSingleClock
from hwt.synthesizer.interfaceLevel.interfaceUtils.utils import walkPhysInterfaces


class TimeDurationStorage(Unit):

    class MODE:
        """
        Select which storage with pending transactions is used.
        """
        IN_ORDER = 0
        OUT_OF_ORDER = 1

    def _config(self) -> None:
        self.ID_WIDTH = Param(6)
        self.TIME_WIDTH:int = Param(32)
        self.ADDR_WIDTH = Param(32)
        self.LEN_WIDTH = Param(Axi4.LEN_WIDTH)

    def _declr(self) -> None:
        addClkRstn(self)
        self.time = Signal(Bits(self.TIME_WIDTH))
        self.mode = Signal()

        # port with data to reserve the transaction id and store
        p = self.push = HsStructIntf()
        p.T = HStruct(
            (Bits(self.ADDR_WIDTH), "addr"),
            (Bits(self.LEN_WIDTH), "len"),
        )

        # port with data to start the transaction
        self.get_trans_exe: Handshaked = HsStructIntf()._m()
        self.get_trans_exe.T = HStruct(
            (Bits(self.ID_WIDTH), "id"),
            (Bits(self.ADDR_WIDTH), "addr"),
            (Bits(self.LEN_WIDTH), "len"),
        )

        # port to mark transaction as complete and load its data
        c = self.mark_trans_complete = Handshaked()
        c.DATA_WIDTH = self.ID_WIDTH

        # port to collect transaction metadata (duration time,)
        trans_stats = self.get_trans_stats = Handshaked()._m()
        trans_stats.DATA_WIDTH = self.TIME_WIDTH

    def _impl(self) -> None:
        push = self.push
        time = self.time

        f = HandshakedFifo(Handshaked)
        f.DEPTH = int(2 ** self.ID_WIDTH)
        f.DATA_WIDTH = self.TIME_WIDTH
        self.fifo = f
        ooof = FifoOutOfOrderRead()
        ooof.ITEMS = f.DEPTH
        self.ooofifo = ooof

        ooof_ram = RamSingleClock()
        ooof_ram.PORT_CNT = (WRITE, READ)

        hs_ram_r = RamAsHs()
        hs_ram_r.HAS_W = False
        hs_ram_w = RamAsHs()
        hs_ram_w.HAS_R = False
        for c in [hs_ram_r, hs_ram_w, ooof_ram]:
            c.ADDR_WIDTH = self.ID_WIDTH
            c.DATA_WIDTH = self.TIME_WIDTH
        self.ooof_ram = ooof_ram
        self.hs_ram_r = hs_ram_r
        self.hs_ram_w = hs_ram_w

        f = self.fifo
        complete = self.mark_trans_complete

        ooof_ram.port[0](hs_ram_w.ram)
        ooof_ram.port[1](hs_ram_r.ram)

        push_tmp = HandshakedReg(push.__class__)
        push_tmp._updateParamsFrom(push)
        self.push_tmp = push_tmp

        get_trans_exe = self.get_trans_exe

        def dissable_inorder_part():
            return (
                f.dataIn.vld(0),
                f.dataIn.data(None),
                f.dataOut.rd(1),
            )

        def dissable_ooo_part():
            return [
                *((_i(0)
                    if _i is i.vld else
                    _i(None)
                    for _i in walkPhysInterfaces(i) if _i._direction == i.vld._direction
                    )
                  for i in [hs_ram_w.w,
                             hs_ram_r.r.addr,
                             ooof.write_confirm,
                             ooof.read_confirm,
                             push_tmp.dataIn]),
                *(i.rd(1)
                  for i in [hs_ram_r.r.data, ooof.read_execute, push_tmp.dataOut]
                )
            ]

        Switch(self.mode)\
        .Case(self.MODE.IN_ORDER,
            f.dataIn.data(time),
            StreamNode([push], [f.dataIn, get_trans_exe]).sync(),
            get_trans_exe.data.id(0),
            get_trans_exe.data(push.data, exclude=[get_trans_exe.data.id]),

            StreamNode([f.dataOut, complete],
                       [self.get_trans_stats, ]).sync(),
            self.get_trans_stats.data(self.time - f.dataOut.data),
            *dissable_ooo_part(),
        ).Case(self.MODE.OUT_OF_ORDER,
            # # allocates id for transaction
            # write_confirm: HandshakeSync
            # # returns the id for transaction
            # read_execute: IndexKeyHs
            # # marks transaction complete
            # read_confirm: Handshaked

            # from input to ooo fifo ram write and trans exec
            StreamNode([push], [push_tmp.dataIn, ooof.write_confirm]).sync(),
            push_tmp.dataIn.data(push.data),

            StreamNode([push_tmp.dataOut, ooof.read_execute],
                       [hs_ram_w.w, get_trans_exe]).sync(),
            hs_ram_w.w.addr(ooof.read_execute.index),
            hs_ram_w.w.data(time),
            get_trans_exe.data.id(ooof.read_execute.index),
            get_trans_exe.data(push_tmp.dataOut.data, exclude=[get_trans_exe.data.id]),

            # from completition port and ooo fifo to ooo fifo ram load
            StreamNode([complete],
                       [hs_ram_r.r.addr, ooof.read_confirm]).sync(),
            hs_ram_r.r.addr.data(complete.data),
            ooof.read_confirm.data(complete.data),

            # from ooo fifo ram to out
            StreamNode([hs_ram_r.r.data],
                       [self.get_trans_stats, ]).sync(),
            self.get_trans_stats.data(self.time - hs_ram_r.r.data.data),
            *dissable_inorder_part(),
        ).Default(
            *dissable_inorder_part(),
            *dissable_ooo_part(),
        )
        propagateClkRstn(self)


if __name__ == "__main__":
    from hwt.synthesizer.utils import to_rtl_str
    u = TimeDurationStorage()
    print(to_rtl_str(u))
