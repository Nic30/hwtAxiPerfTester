#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from typing import Tuple, Union, Dict

from hwt.code import If
from hwt.hdl.types.bits import Bits
from hwt.hdl.types.defs import BIT
from hwt.hdl.types.hdlType import HdlType
from hwt.hdl.types.struct import HStruct, HStructField
from hwt.interfaces.hsStructIntf import HsStructIntf
from hwt.interfaces.std import HandshakeSync
from hwt.interfaces.structIntf import StructIntf
from hwt.interfaces.utils import addClkRstn, propagateClkRstn
from hwt.synthesizer.interface import Interface
from hwt.synthesizer.param import Param
from hwt.synthesizer.rtlLevel.rtlSyncSignal import RtlSyncSignal
from hwt.synthesizer.unit import Unit
from hwtLib.abstract.busEndpoint import BusEndpoint
from hwtLib.amba.axi4 import Axi4
from hwtLib.handshaked.streamNode import StreamNode
from hwtLib.logic.crcComb import CrcComb
from hwtLib.logic.crcPoly import CRC_8, CRC_32
from hwt.hdl.constants import READ, WRITE


class AddressGenerator(Unit):

    class MODE:
        MODULO = 0
        CRC = 1

    def _config(self) -> None:
        self.ADDR_WIDTH = Param(32)
        self.LEN_WIDTH = Param(Axi4.LEN_WIDTH)

    def _declr(self) -> None:
        addClkRstn(self)

        self.en = HandshakeSync()
        self.req_out: HsStructIntf = HsStructIntf()._m()
        self.req_out.T = HStruct(
            (Bits(self.ADDR_WIDTH), "addr"),
            (Bits(self.LEN_WIDTH), "len"),
        )

        addr_t = self.addr_t = Bits(self.ADDR_WIDTH)
        len_t = self.len_t = Bits(self.LEN_WIDTH)
        self.ADDR_SPACE = HStruct(
            (addr_t, "addr"),
            (addr_t, "addr_step"),
            (addr_t, "addr_mask"),
            (BIT, "addr_mode"),
            (addr_t, "addr_offset"),

            (len_t, "trans_len"),
            (len_t, "trans_len_step"),
            (len_t, "trans_len_mask"),
            (BIT, "trans_len_mode"),
        )
        self.STRUCT_TEMPLATE = self.ADDR_SPACE
        self.addr_space_io = StructIntf(
            self.ADDR_SPACE, tuple(),
            instantiateFieldFn=self._mkFieldInterface)

    @staticmethod
    def shouldEnterFn(root: HdlType, field_path: Tuple[Union[str, int]]):
        return BusEndpoint._defaultShouldEnterFn(root, field_path)

    def _mkFieldInterface(self, structIntf: StructIntf, field: HStructField):
        return BusEndpoint._mkFieldInterface(self, structIntf, field)

    def propagate_addr_space(self, data: Dict[str, Union[RtlSyncSignal, Interface]], read_or_write):
        res = []
        for io in self.addr_space_io._interfaces:
            reg = data[io._name]
            if read_or_write == READ:
                o = io.din(reg)
            else:
                o = If(io.dout.vld,
                   reg(io.dout.data),
                )

            res.append(o)

        return res

    def _impl(self) -> None:
        addr_t = self.addr_t

        addr = self._reg("addr", addr_t)
        addr_step = self._reg("addr_step", addr_t)
        addr_mask = self._reg("addr_mask", addr_t)
        addr_mode = self._reg("addr_mode")
        addr_offset = self._reg("addr_offset", addr_t)

        addr_crc32 = CrcComb()
        addr_crc32.DATA_WIDTH = self.ADDR_WIDTH
        addr_crc32.setConfig(CRC_32)
        self.addr_crc32 = addr_crc32
        addr_crc32.dataIn(addr)

        len_t = Bits(self.LEN_WIDTH)
        trans_len = self._reg("trans_len", len_t)
        trans_len_step = self._reg("trans_len_step", len_t)
        trans_len_mask = self._reg("trans_len_mask", len_t)
        trans_len_mode = self._reg("trans_len_mode")
        trans_len_crc8 = CrcComb()
        trans_len_crc8.DATA_WIDTH = self.LEN_WIDTH
        trans_len_crc8.setConfig(CRC_8)
        self.trans_len_crc8 = trans_len_crc8
        trans_len_crc8.dataIn(trans_len)

        req_out = self.req_out
        sync = StreamNode([self.en], [req_out])
        sync.sync()

        self.propagate_addr_space(locals(), READ)
        If(sync.ack(),
            If(addr_mode._eq(self.MODE.MODULO),
               addr(addr + addr_step),
            ).Elif(addr_mode._eq(self.MODE.CRC),
               addr(addr_crc32.dataOut),
            ),
            If(trans_len_mode._eq(self.MODE.MODULO),
               trans_len((trans_len + trans_len_step)),
            ).Elif(trans_len_mode._eq(self.MODE.CRC),
               trans_len(trans_len_crc8.dataOut),
            ),
        ).Else(
            *self.propagate_addr_space(locals(), WRITE)
        )

        req_out.data.addr((addr & addr_mask) + addr_offset)
        req_out.data.len(trans_len & trans_len_mask)
        propagateClkRstn(self)


if __name__ == "__main__":
    from hwt.synthesizer.utils import to_rtl_str
    u = AddressGenerator()
    print(to_rtl_str(u))
