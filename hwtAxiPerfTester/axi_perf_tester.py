#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from typing import Type, Tuple, Optional

from hwt.code import If
from hwt.hdl.types.bits import Bits
from hwt.hdl.types.defs import BIT
from hwt.hdl.types.hdlType import HdlType
from hwt.hdl.types.struct import HStruct
from hwt.interfaces.std import HandshakeSync
from hwt.interfaces.structIntf import StructIntf
from hwt.interfaces.utils import addClkRstn, propagateClkRstn
from hwt.synthesizer.hObjList import HObjList
from hwt.synthesizer.param import Param
from hwt.synthesizer.rtlLevel.rtlSignal import RtlSignal
from hwt.synthesizer.unit import Unit
from hwtAxiPerfTester.transaction_generator import TransactionGenerator
from hwtAxiPerfTester.rw_pattern_generator import RWPatternGenerator
from hwtAxiPerfTester.statistic_collector import StatisticCollector
from hwtAxiPerfTester.time_duration_storage import TimeDurationStorage
from hwtLib.amba.axi4 import Axi4, Axi4_addr
from hwtLib.amba.axi4Lite import Axi4Lite
from hwtLib.amba.axiLite_comp.endpoint import AxiLiteEndpoint
from hwtLib.amba.constants import BURST_INCR, PROT_DEFAULT, BYTES_IN_TRANS, \
    LOCK_DEFAULT, CACHE_DEFAULT, QOS_DEFAULT
from hwtLib.handshaked.streamNode import StreamNode
from hwtLib.types.ctypes import uint32_t, uint16_t, uint64_t
from pyMathBitPrecise.bit_utils import mask


class AxiPerfTester(Unit):
    """
    This component is a performace tester for AXI3/4 slaves.
    It can be configured to generate various access patterns and measures througput and latency of operations.
    :see: :class:`hwtAxiPerfTester.transaction_generator.TransactionGenerator`
    The output is in format of histogram, last n values and several common properties like min/max etc.
    :see: :class:`hwtAxiPerfTester.statistic_collector.StatisticCollector`.


    .. figure:: ./_static/AxiPerfTester.png

    .. hwt-autodoc::
    """

    def _config(self) -> None:
        # generator/stat collector config
        self.COUNTER_WIDTH:int = Param(32)
        self.RW_PATTERN_ITEMS:int = Param(1024)
        self.HISTOGRAM_ITEMS:int = Param(32)
        self.LAST_VALUES_ITEMS = Param(4096)

        # cfg bus config
        self.CFG_ADDR_WIDTH:int = Param(32)
        self.CFG_DATA_WIDTH:int = Param(32)
        # self.CFG_BUS:Tuple[Type, Type] = Param((Mi32, Mi32Endpoint))
        self.CFG_BUS:Tuple[Type, Type] = Param((Axi4Lite, AxiLiteEndpoint))

        # axi config
        self.AXI_CLS:Type = Param(Axi4)
        self.ID_WIDTH:int = Param(6)
        self.ADDR_WIDTH:int = Param(32)
        self.DATA_WIDTH:int = Param(512)
        self.MAX_BLOCK_DATA_WIDTH: Optional[int] = Param(None)

    def _declr(self) -> None:
        addClkRstn(self)
        cfg = self.cfg = self.CFG_BUS[0]()
        cfg.ADDR_WIDTH = self.CFG_ADDR_WIDTH
        cfg.DATA_WIDTH = self.CFG_DATA_WIDTH

        with self._paramsShared():
            self.axi = self.AXI_CLS()._m()

    def _axi_addr_defaults(self, a: Axi4_addr):
        a.burst(BURST_INCR)
        a.prot(PROT_DEFAULT)
        a.size(BYTES_IN_TRANS(self.DATA_WIDTH // 8))

        a.lock(LOCK_DEFAULT)
        a.cache(CACHE_DEFAULT)
        a.qos(QOS_DEFAULT)

    def add_channel(self, name:str, axi_addr: Axi4_addr, cfg_io: StructIntf,
                    time: RtlSignal, stats_en: RtlSignal,
                    generator_en: HandshakeSync, ordering_mode: RtlSignal):
        addr_gen = TransactionGenerator()
        trans_store = TimeDurationStorage()
        stats = StatisticCollector()
        stats.COUNTER_WIDTH = self.COUNTER_WIDTH
        stats.TRANS_ID_WIDTH = self.ID_WIDTH
        stats.HISTOGRAM_ITEMS = self.HISTOGRAM_ITEMS
        stats.LAST_VALUES_ITEMS = self.LAST_VALUES_ITEMS

        self.TIME_WIDTH:int = Param(32)

        for ag in [addr_gen, trans_store]:
            ag.ADDR_WIDTH = self.ADDR_WIDTH
            ag.LEN_WIDTH = self.AXI_CLS.LEN_WIDTH

        trans_store.ID_WIDTH = self.ID_WIDTH
        trans_store.TIME_WIDTH = self.COUNTER_WIDTH

        setattr(self, f"{name:s}_addr_gen", addr_gen)
        setattr(self, f"{name:s}_trans_store", trans_store)
        setattr(self, f"{name:s}_stats", stats)

        addr_gen.en(generator_en)
        trans_store.push(addr_gen.req_out)
        trans_store.mode(ordering_mode)
        trans_store.time(time)

        self._axi_addr_defaults(axi_addr)
        t_exe = trans_store.get_trans_exe

        axi_addr.id(t_exe.data.id)
        axi_addr.addr(t_exe.data.addr)
        axi_addr.len(t_exe.data.len)

        dispatched_cntr = self._reg("dispatched_cntr", Bits(self.COUNTER_WIDTH))
        If(cfg_io.dispatched_cntr.dout.vld,
            dispatched_cntr(cfg_io.dispatched_cntr.dout.data),
        ).Else(
            If(axi_addr.valid & axi_addr.ready,
               dispatched_cntr(dispatched_cntr + 1)
            )
        )
        cfg_io.dispatched_cntr.din(dispatched_cntr)

        # trans_store -> axi data -> stats
        complete = trans_store.mark_trans_complete
        if axi_addr is self.axi.aw:
            data_cntr = self._reg(
                "w_data_cntr",
                HStruct(
                    (BIT, "vld"),
                    (Bits(self.AXI_CLS.LEN_WIDTH), "val"),
                ),
                def_val={"vld": 0}
            )
            w = self.axi.w
            data_cntr_ld = ~data_cntr.vld | (data_cntr.val._eq(0) & w.ready)
            StreamNode(
                [t_exe, ],
                [axi_addr, ]
            ).sync(data_cntr_ld)

            If(data_cntr_ld,
               data_cntr.vld(t_exe.vld),
               data_cntr.val(t_exe.data.len),
            ).Elif(w.ready,
               data_cntr.val(data_cntr.val - 1),
            )
            w.strb(mask(w.strb._dtype.bit_length()))
            w.data(data_cntr.val, fit=True)
            w.last(data_cntr.val._eq(0))
            w.valid(data_cntr.vld)

            b = self.axi.b
            complete.data(b.id)
            StreamNode([b], [complete]).sync()

        else:
            StreamNode(
                [t_exe, ],
                [axi_addr]
            ).sync()

            assert axi_addr is self.axi.ar, axi_addr
            r = self.axi.r
            complete.vld(r.valid & r.last)
            r.ready(complete.rd)
            complete.data(r.id)

        addr_gen.addr_space_io(cfg_io.addr_gen_config, exclude=[cfg_io.addr_gen_config.credit, ], fit=True)

        stats.en(stats_en)
        stats.time(time)
        stats.trans_stats(trans_store.get_trans_stats)
        stats.histogram_keys(cfg_io.stats.histogram_keys)
        stats.histogram_counters(cfg_io.stats.histogram_counters)

        stats.last_values(cfg_io.stats.last_values)
        stats.cntr_io(HObjList([
            cfg_io.stats.min_val,
            cfg_io.stats.max_val,
            cfg_io.stats.sum_val,
            cfg_io.stats.input_cnt,
            cfg_io.stats.last_time,
        ]), fit=True)

    def build_addr_decoder(self, ADDR_SPACE: HdlType):
        cfg_decoder = self.CFG_BUS[1](ADDR_SPACE)
        cfg_decoder.ADDR_WIDTH = self.CFG_ADDR_WIDTH
        cfg_decoder.DATA_WIDTH = self.CFG_DATA_WIDTH

        self.cfg_decoder = cfg_decoder
        cfg_decoder.bus(self.cfg)
        cfg = cfg_decoder.decoded
        return cfg

    def construct_addr_space_type(self):
        addr_gen_config_t = HStruct(
            (uint32_t, "credit"),
            (uint32_t, "addr"),
            (uint32_t, "addr_step"),
            (uint32_t, "addr_mask"),
            (uint32_t, "addr_mode"),
            (uint32_t, "addr_offset"),

            (uint32_t, "trans_len"),
            (uint32_t, "trans_len_step"),
            (uint32_t, "trans_len_mask"),
            (uint32_t, "trans_len_mode"),
            name="addr_gen_config_t",
        )
        stat_data_t = HStruct(
            (uint32_t[self.HISTOGRAM_ITEMS - 1], "histogram_keys"),
            (uint32_t[self.HISTOGRAM_ITEMS], "histogram_counters"),
            (uint32_t[self.LAST_VALUES_ITEMS], "last_values"),
            (uint32_t, "min_val"),
            (uint32_t, "max_val"),
            (uint32_t, "sum_val"),
            (uint32_t, "input_cnt"),
            (uint32_t, "last_time"),
            name="stat_data_t",
        )
        channel_config_t = HStruct(
            (uint32_t[self.RW_PATTERN_ITEMS * 2], "pattern"),
            (uint32_t, "dispatched_cntr"),
            (addr_gen_config_t, "addr_gen_config"),
            (stat_data_t, "stats"),
            name="channel_config_t"
        )
        control_t = HStruct(
            (BIT, "time_en"),
            (BIT, "rw_mode"),
            (BIT, "generator_en"),
            (BIT, "r_ordering_mode"),
            (BIT, "w_ordering_mode"),
            (Bits(32 - 5), "reserved"),
            name="control_t"
        )
        serialized_config_t = HStruct(
            (uint16_t, "COUNTER_WIDTH"),
            (uint16_t, "RW_PATTERN_ITEMS"),
            (uint16_t, "HISTOGRAM_ITEMS"),
            (uint16_t, "LAST_VALUES_ITEMS"),
            (uint16_t, "ID_WIDTH"),
            (uint16_t, "ADDR_WIDTH"),
            (uint16_t, "DATA_WIDTH"),
            (uint16_t, None),
            name="serialized_config_t"
        )
        ADDR_SPACE = HStruct(
            (uint32_t, "id"),  # "TEST"
            (uint32_t, "control"),  # :see: control_t
            (uint32_t, "time"),  # global time in this component
            (serialized_config_t, "serialized_config"),
            (channel_config_t, "r"),
            (channel_config_t, "w"),
        )
        return  ADDR_SPACE, control_t

    def _impl(self) -> None:
        ADDR_SPACE, control_t = self.construct_addr_space_type()
        # print(ADDR_SPACE)
        cfg = self.build_addr_decoder(ADDR_SPACE)
        cfg.id.din(int.from_bytes("TEST".encode(), "big"))
        for sc in cfg.serialized_config._interfaces:
            sc.din(getattr(self, sc._name))

        cntrl = self._reg("cntrl", HStruct(
            (BIT, "time_en"),
            (BIT, "rw_mode"),
            (BIT, "r_ordering_mode"),
            (BIT, "w_ordering_mode"),
        ), def_val={
            "time_en":0,
            "rw_mode": RWPatternGenerator.MODE.SYNC,
            "r_ordering_mode": TimeDurationStorage.MODE.IN_ORDER,
            "w_ordering_mode": TimeDurationStorage.MODE.IN_ORDER,
        })

        time = self._reg("time", Bits(self.COUNTER_WIDTH))

        If(cfg.time.dout.vld,
           time(cfg.time.dout.data),
        ).Elif(cntrl.time_en,
           time(time + 1)
        )
        cfg.time.din(time)

        rw_pat = RWPatternGenerator()
        rw_pat.MAX_BLOCK_DATA_WIDTH = self.MAX_BLOCK_DATA_WIDTH
        rw_pat.ADDR_WIDTH = self.ADDR_WIDTH
        rw_pat.ITEMS = self.RW_PATTERN_ITEMS
        rw_pat.COUNTER_WIDTH = self.COUNTER_WIDTH
        self.rw_pattern_gen = rw_pat
        rw_pat.r_pattern(cfg.r.pattern, fit=True)
        rw_pat.w_pattern(cfg.w.pattern, fit=True)
        rw_pat.mode(cntrl.rw_mode)

        cfg_control_din = cfg.control.din._reinterpret_cast(control_t)
        cfg_control_dout = cfg.control.dout.data._reinterpret_cast(control_t)
        self.add_channel("r", self.axi.ar, cfg.r, time, cntrl.time_en, rw_pat.r_en, cntrl.r_ordering_mode)
        rw_pat.r_credit(cfg.r.addr_gen_config.credit)
        self.add_channel("w", self.axi.aw, cfg.w, time, cntrl.time_en, rw_pat.w_en, cntrl.w_ordering_mode)
        rw_pat.w_credit(cfg.w.addr_gen_config.credit)

        If(cfg.control.dout.vld,
           cntrl.time_en(cfg_control_dout.time_en),
           cntrl.rw_mode(cfg_control_dout.rw_mode),
           cntrl.r_ordering_mode(cfg_control_dout.r_ordering_mode),
           cntrl.w_ordering_mode(cfg_control_dout.w_ordering_mode),
        )
        rw_pat.en.dout.vld(cfg.control.dout.vld)
        rw_pat.en.dout.data(cfg_control_dout.generator_en)
        cfg_control_din(cntrl, exclude=[cfg_control_din.generator_en, cfg_control_din.reserved])
        cfg_control_din.generator_en(rw_pat.en.din)
        cfg_control_din.reserved(0)

        propagateClkRstn(self)


if __name__ == "__main__":
    from hwt.synthesizer.utils import to_rtl_str
    u = AxiPerfTester()
    u.HISTOGRAM_ITEMS = 4
    u.LAST_VALUES_ITEMS = 4
    u.ID_WIDTH = 4
    u.RW_PATTERN_ITEMS = 4
    u.DATA_WIDTH = 32
    print(to_rtl_str(u))

