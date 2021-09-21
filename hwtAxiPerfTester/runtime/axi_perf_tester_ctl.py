
import time
from typing import List, Tuple

from hwtAxiPerfTester.address_generator import AddressGenerator
from hwtAxiPerfTester.rw_pattern_generator import RWPatternGenerator
from hwtAxiPerfTester.time_duration_storage import TimeDurationStorage
from pyMathBitPrecise.bit_utils import mask


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
        self.addr_mask = 0x1000
        self.addr_mode = AddressGenerator.MODE.MODULO
        self.addr_offset = 0x0
        self.trans_len = 0
        self.trans_len_step = 0
        self.trans_len_mask = 1
        self.trans_len_mode = AddressGenerator.MODE.MODULO


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


class AxiPerfTesterTestChannelReport():
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
        self.last_values: List[int] = []
        self.min_val = 0
        self.max_val = 0
        self.sum_val = 0
        self.input_cnt = 0
        self.last_time = 0


class AxiPerfTesterCtl():
    """
    .. code-block:: text

        struct {
            <Bits, 32bits, unsigned> id
            <Bits, 32bits, unsigned> controll
            <Bits, 32bits, unsigned> time
            struct channel_config_t {
                <Bits, 32bits, unsigned>[1024] pattern
                <Bits, 32bits, unsigned> dispatched_cntr
                struct addr_gen_config_t {
                    <Bits, 32bits, unsigned> credit
                    <Bits, 32bits, unsigned> addr
                    <Bits, 32bits, unsigned> addr_step
                    <Bits, 32bits, unsigned> addr_mask
                    <Bits, 32bits, unsigned> addr_mode
                    <Bits, 32bits, unsigned> addr_offset
                    <Bits, 32bits, unsigned> trans_len
                    <Bits, 32bits, unsigned> trans_len_step
                    <Bits, 32bits, unsigned> trans_len_mask
                    <Bits, 32bits, unsigned> trans_len_mode
                } addr_gen_config
                struct stat_data_t {
                    <Bits, 32bits, unsigned>[31] histogram_keys
                    <Bits, 32bits, unsigned>[32] histogram_counters
                    <Bits, 32bits, unsigned>[4096] last_values
                    <Bits, 32bits, unsigned> min_val
                    <Bits, 32bits, unsigned> max_val
                    <Bits, 32bits, unsigned> sum_val
                    <Bits, 32bits, unsigned> input_cnt
                    <Bits, 32bits, unsigned> last_time
                } stats
            } r
            struct channel_config_t {...
            } w
        }
"""

    def __init__(self, addr: int, rw_pattern_items: int,
                 histogram_items:int, last_values_items: int, pooling_interval=0.1):
        # constant intitialization
        self.addr = addr
        self.pooling_interval = pooling_interval
        self.rw_pattern_items = rw_pattern_items
        self.histogram_items = histogram_items
        self.last_values_items = last_values_items
        self.channels_offset = 3 * 4
        self.dispatched_cntr_offset = self.channels_offset + rw_pattern_items * 4
        self.addr_gen_config_t_size = 10 * 4
        self.addr_gen_config_offset = self.dispatched_cntr_offset + 4
        self.stat_data_offset = self.addr_gen_config_offset + self.addr_gen_config_t_size
        self.stat_data_size = (self.histogram_items * 2 - 1 + self.last_values_items + 5) * 4
        self.channel_config_t_size = rw_pattern_items * 4 + 4 + self.addr_gen_config_t_size + self.stat_data_size

    def write_controll(self, time_en:int,
                       rw_mode: RWPatternGenerator.MODE,
                       generator_en: int,
                       r_ordering_mode:TimeDurationStorage.MODE,
                       w_ordering_mode:TimeDurationStorage.MODE,
                       reset_time:bool):
        assert time_en in (0, 1), time_en
        assert rw_mode in (0, 1), rw_mode
        assert generator_en in (0, 1), generator_en
        assert r_ordering_mode in (0, 1), r_ordering_mode
        assert w_ordering_mode in (0, 1), w_ordering_mode

        v = 0
        for b in (w_ordering_mode, r_ordering_mode, generator_en, rw_mode, time_en):
            v <<= 1
            v |= b

        self.write32(4, v)
        if reset_time:
            self.write32(2 * 4, 0)

    def get_time(self) -> int:
        return self.read32(2 * 4)

    def apply_config(self, config: AxiPerfTesterTestJob):
        write32 = self.write32
        # copy rw pattern
        for ch_i, ch in enumerate(config.channel_config):
            ch: AxiPerfTesterChannelConfig
            offset = self.channel_config_t_size * ch_i
            assert len(ch.pattern) == self.rw_pattern_items
            for i, en in enumerate(ch.pattern):
                write32(offset + self.channels_offset + i * 4, en)

            # reset dispatched_cntr
            write32(offset + self.dispatched_cntr_offset, 0)

            # copy addr_gen_config
            for i, name in enumerate([
                    "credit",
                    "addr",
                    "addr_step",
                    "addr_mask",
                    "addr_mode",
                    "addr_offset",
                    "trans_len",
                    "trans_len_step",
                    "trans_len_mask",
                    "trans_len_mode",
                ]):
                v = getattr(ch.addr_gen, name)
                write32(offset + self.addr_gen_config_offset + i * 4, v)

            # init histogram keys and clean counter
            # struct stat_data_t {
            #    <Bits, 32bits, unsigned>[31] histogram_keys
            #    <Bits, 32bits, unsigned>[32] histogram_counters
            #    <Bits, 32bits, unsigned>[4096] last_values
            #    <Bits, 32bits, unsigned> min_val
            #    <Bits, 32bits, unsigned> max_val
            #    <Bits, 32bits, unsigned> sum_val
            #    <Bits, 32bits, unsigned> input_cnt
            #    <Bits, 32bits, unsigned> last_time
            # } stats
            assert len(ch.stat_config.histogram_keys) == self.histogram_items - 1, (len(ch.stat_config.histogram_keys), self.histogram_items - 1)
            for i, v in enumerate(ch.stat_config.histogram_keys):
                write32(offset + self.stat_data_offset + i * 4, v)

            min_val_i = self.histogram_items + self.last_values_items
            for i in range(self.histogram_items + self.last_values_items + 5):
                if i == min_val_i:
                    v = mask(32)
                else:
                    v = 0
                write32(offset + self.stat_data_offset + (self.histogram_items - 1 + i) * 4, v)

    def is_generator_running(self) -> bool:
        return (self.read32(4) >> 2) & 0b1

    def get_pending_trans_cnt(self, ch_i: int):
        offset = self.channel_config_t_size * ch_i
        dispatched_cntr = self.read32(offset + self.dispatched_cntr_offset)
        input_cnt = self.read32(offset + self.stat_data_offset + (self.histogram_items * 2 - 1 + self.last_values_items + 3) * 4)

        res = dispatched_cntr - input_cnt
        assert res >= 0
        return res

    def download_channel_report(self, ch_i: int, rep: AxiPerfTesterTestChannelReport):
        read32 = self.read32
        offset = self.channel_config_t_size * ch_i
        rep.credit = read32(offset + self.addr_gen_config_offset)
        rep.dispatched_cntr = read32(offset + self.dispatched_cntr_offset)

        offset += self.stat_data_offset + (self.histogram_items - 1) * 4
        rep.histogram_counters: List[int] = [
            read32(offset + i * 4) for i in range(self.histogram_items)
        ]

        offset += self.histogram_items * 4
        rep.last_values: List[int] = [
            read32(offset + i * 4) for i in range(self.last_values_items)
        ]

        offset += self.last_values_items * 4
        rep.min_val, rep.max_val, rep.sum_val, rep.input_cnt, rep.last_time = [
            read32(offset + i * 4) for i in range(5)
        ]

    def exec_test(self, job: AxiPerfTesterTestJob) -> AxiPerfTesterTestReport:
        _id = self.read32(0)
        _id_ref = int.from_bytes("TEST".encode(), "big")
        assert _id == _id_ref, (f"got {_id:x}, expected {_id_ref:x}")
        self.write_controll(
            0, job.rw_mode, 0,
            job.channel_config[0].addr_gen.ordering_mode,
            job.channel_config[1].addr_gen.ordering_mode, True)
        # reset time
        self.write32(2 * 4, 0)

        self.apply_config(job)
        self.write_controll(
            1, job.rw_mode, 1,
            job.channel_config[0].addr_gen.ordering_mode,
            job.channel_config[1].addr_gen.ordering_mode, False)

        while self.is_generator_running() or \
                self.get_pending_trans_cnt(0) > 0 or\
                self.get_pending_trans_cnt(1) > 0:
            time.sleep(self.pooling_interval)
        self.write_controll(
            0, job.rw_mode, 0,
            job.channel_config[0].addr_gen.ordering_mode,
            job.channel_config[1].addr_gen.ordering_mode, False)

        rep = AxiPerfTesterTestReport()
        rep.time = self.get_time()
        for ch_i, ch_rep in enumerate(rep.channel):
            self.download_channel_report(ch_i, ch_rep)

        return rep

    def read32(self, addr: int):
        return int.from_bytes(self.read(addr, 4), 'little')

    def read(self, addr: int, size: int) -> int:
        raise NotImplementedError("Overide in your implementation")

    def write32(self, addr:int, data: int):
        return self.write(addr, 4, data)

    def write(self, addr:int, size:int, data:int):
        raise NotImplementedError("Overide in your implementation")
