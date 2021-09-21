#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from typing import Tuple, Type

from hwt.hdl.types.hdlType import HdlType
from hwtAxiPerfTester.axi_perf_tester import AxiPerfTester
from hwtLib.cesnet.mi32.endpoint import Mi32Endpoint
from hwtLib.cesnet.mi32.intf import Mi32
from hwtLib.cesnet.mi32.builder import Mi32Builder


class AxiPerfTesterMi32(AxiPerfTester):

    def _config(self) -> None:
        super(AxiPerfTesterMi32, self)._config()
        self.CFG_BUS:Tuple[Type, Type] = (Mi32, Mi32Endpoint)

    def build_addr_decoder(self, ADDR_SPACE: HdlType):
        cfg_decoder = self.CFG_BUS[1](ADDR_SPACE)
        cfg_decoder.ADDR_WIDTH = self.CFG_ADDR_WIDTH
        cfg_decoder.DATA_WIDTH = self.CFG_DATA_WIDTH

        self.cfg_decoder = cfg_decoder
        cfg_decoder.bus(Mi32Builder(self, self.cfg).buff(1, 1).end)
        cfg = cfg_decoder.decoded
        return cfg


if __name__ == "__main__":
    from hwt.synthesizer.utils import to_rtl_str
    u = AxiPerfTesterMi32()
    print(to_rtl_str(u))
