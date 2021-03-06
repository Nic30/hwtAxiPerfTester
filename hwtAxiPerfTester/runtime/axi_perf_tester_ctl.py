
import struct
import time
from typing import List

from hwtAxiPerfTester.runtime.data_containers import AxiPerfTesterTestJob, \
    AxiPerfTesterChannelConfig, AxiPerfTesterTestChannelReport, \
    AxiPerfTesterTestReport
from hwtAxiPerfTester.rw_pattern_generator import RWPatternGenerator
from hwtAxiPerfTester.time_duration_storage import TimeDurationStorage
from pyMathBitPrecise.bit_utils import mask


class AxiPerfTesterCtl():
    """
    A base class which contains an application logic of a driver of AxiPerfTester
    * needs inplementation of read/write method in order to work


    The component address space looks like:

    .. code-block:: text

        struct {
            <Bits, 32bits, unsigned> id
            <Bits, 32bits, unsigned> control
            <Bits, 32bits, unsigned> time
            struct serialized_config_t {
                <Bits, 16bits, unsigned> COUNTER_WIDTH
                <Bits, 16bits, unsigned> RW_PATTERN_ITEMS
                <Bits, 16bits, unsigned> HISTOGRAM_ITEMS
                <Bits, 16bits, unsigned> LAST_VALUES_ITEMS
                <Bits, 16bits, unsigned> ID_WIDTH
                <Bits, 16bits, unsigned> ADDR_WIDTH
                <Bits, 16bits, unsigned> DATA_WIDTH
                //<Bits, 16bits, unsigned> empty space
            } serialized_config
            struct channel_config_t {
                <Bits, 32bits, unsigned>[4] pattern
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
                    <Bits, 32bits, unsigned>[3] histogram_keys
                    <Bits, 32bits, unsigned>[4] histogram_counters
                    <Bits, 32bits, unsigned>[4] last_values
                    <Bits, 32bits, unsigned> min_val
                    <Bits, 32bits, unsigned> max_val
                    <Bits, 32bits, unsigned> sum_val
                    <Bits, 32bits, unsigned> input_cnt
                    <Bits, 32bits, unsigned> last_time
                } stats
            } r
            struct channel_config_t {
                // identiacal as "r"
            } w
        }
        struct control_t {
            <Bits, 1bit> time_en
            <Bits, 1bit> rw_mode
            <Bits, 1bit> generator_en
            <Bits, 1bit> r_ordering_mode
            <Bits, 1bit> w_ordering_mode
            <Bits, 27bits> reserved
        }
"""

    def __init__(self, addr: int, pooling_interval=0.1):
        # constant intitialization
        self.addr = addr
        self.pooling_interval = pooling_interval
        self.config_loaded = False

    def _load_config(self):
        """
        Query the hardware for configuration of the tester and store this information for later use.
        """
        config = self.read(3 * 4, 4 * 2)
        # <Bits, 16bits, unsigned> COUNTER_WIDTH
        # <Bits, 16bits, unsigned> RW_PATTERN_ITEMS
        # <Bits, 16bits, unsigned> HISTOGRAM_ITEMS
        # <Bits, 16bits, unsigned> LAST_VALUES_ITEMS

        _, rw_pattern_items, histogram_items, last_values_items = struct.unpack('<HHHH', config)
        self.rw_pattern_items = rw_pattern_items
        self.histogram_items = histogram_items
        self.last_values_items = last_values_items
        self.channels_offset = 3 * 4 + 8 * 2
        self.dispatched_cntr_offset = self.channels_offset + rw_pattern_items * 8
        self.addr_gen_config_t_size = 10 * 4
        self.addr_gen_config_offset = self.dispatched_cntr_offset + 4
        self.stat_data_offset = self.addr_gen_config_offset + self.addr_gen_config_t_size
        self.stat_data_size = (self.histogram_items * 2 - 1 + self.last_values_items + 5) * 4
        self.channel_config_t_size = rw_pattern_items * 8 + 4 + self.addr_gen_config_t_size + self.stat_data_size
        self.config_loaded = True

    def write_control(self, time_en:int,
                       rw_mode: RWPatternGenerator.MODE,
                       generator_en: int,
                       r_ordering_mode:TimeDurationStorage.MODE,
                       w_ordering_mode:TimeDurationStorage.MODE,
                       reset_time:bool):
        """
        Write control word in control register.
        """
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
        """
        Get time from the component
        """
        return self.read32(2 * 4)

    def apply_config(self, config: AxiPerfTesterTestJob):
        """
        Upload config to tester.
        """
        write32 = self.write32
        # copy rw pattern
        for ch_i, ch in enumerate(config.channel_config):
            ch: AxiPerfTesterChannelConfig
            offset = self.channel_config_t_size * ch_i
            assert len(ch.pattern) == self.rw_pattern_items
            for i, (addr, delay, en) in enumerate(ch.pattern):
                o = offset + self.channels_offset + i * 8
                write32(o, addr)
                write32(o + 4, delay | (en << 16))

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
        """
        Retrun True if transaction generator is still running.
        """
        return (self.read32(4) >> 2) & 0b1

    def get_pending_trans_cnt(self, ch_i: int):
        """
        Get number of transactions which are actually executed and waiting to be finished.
        """
        offset = self.channel_config_t_size * ch_i
        dispatched_cntr = self.read32(offset + self.dispatched_cntr_offset)
        input_cnt = self.read32(offset + self.stat_data_offset + (self.histogram_items * 2 - 1 + self.last_values_items + 3) * 4)

        res = dispatched_cntr - input_cnt
        assert res >= 0
        return res

    def download_channel_report(self, ch_i: int, histogram_keys: List[int], rep: AxiPerfTesterTestChannelReport):
        """
        Download all counters histograms and other report registers for specific channel.
        """
        read32 = self.read32
        offset = self.channel_config_t_size * ch_i
        rep.credit = read32(offset + self.addr_gen_config_offset)
        rep.dispatched_cntr = read32(offset + self.dispatched_cntr_offset)

        rep.histogram_keys = histogram_keys
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
        """
        Run test/benchmark according to job specification.
        """
        if not self.config_loaded:
            self._load_config()

        _id = self.read32(0)
        _id_ref = int.from_bytes("TEST".encode(), "big")
        assert _id == _id_ref, (f"got {_id:x}, expected {_id_ref:x}")
        self.write_control(
            0, job.rw_mode, 0,
            job.channel_config[0].addr_gen.ordering_mode,
            job.channel_config[1].addr_gen.ordering_mode, True)
        # reset time
        self.write32(2 * 4, 0)

        self.apply_config(job)
        self.write_control(
            1, job.rw_mode, 1,
            job.channel_config[0].addr_gen.ordering_mode,
            job.channel_config[1].addr_gen.ordering_mode, False)

        while self.is_generator_running() or \
                self.get_pending_trans_cnt(0) > 0 or\
                self.get_pending_trans_cnt(1) > 0:
            time.sleep(self.pooling_interval)
        self.write_control(
            0, job.rw_mode, 0,
            job.channel_config[0].addr_gen.ordering_mode,
            job.channel_config[1].addr_gen.ordering_mode, False)

        rep = AxiPerfTesterTestReport()
        rep.time = self.get_time()
        for ch_i, ch_rep in enumerate(rep.channel):
            self.download_channel_report(ch_i, job.channel_config[ch_i].stat_config.histogram_keys, ch_rep)

        return rep

    def read32(self, addr: int) -> int:
        return int.from_bytes(self.read(addr, 4), 'little')

    def read(self, addr: int, size: int) -> bytes:
        raise NotImplementedError("Override in your implementation")

    def write32(self, addr:int, data: int):
        return self.write(addr, 4, data)

    def write(self, addr:int, size:int, data:int):
        raise NotImplementedError("Override in your implementation")
