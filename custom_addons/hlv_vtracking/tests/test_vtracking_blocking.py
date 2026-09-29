"""Test cờ chặn. Chạy KHÔNG cần Odoo — xem lệnh ở đầu ``test_vtracking_route.py``.

Sai ở đây có hai kiểu hỏng, ngược chiều nhau: xe tới cổng khu chế xuất mà chưa khai hải
quan thì phải chở hàng về; còn chặn nhầm thì đơn nằm lại kho vô thời hạn mà không ai biết
vì sao.
"""

import unittest

try:
    from . import standalone
except ImportError:  # chạy bằng python trần: thư mục tests là gốc
    import standalone

blocking = standalone.load_tool('vtracking_blocking')


class TestThuTuc(unittest.TestCase):

    def test_khach_can_hai_quan_thi_chan_cung(self):
        flags = blocking.blocking_flags('customs')
        self.assertTrue(blocking.has_hard_block(flags))

    def test_both_sinh_hai_co(self):
        codes = [flag['code'] for flag in blocking.blocking_flags('both')]
        self.assertEqual(sorted(codes), ['customs', 'register'])

    def test_bao_xong_thu_tuc_thi_het_chan(self):
        flags = blocking.blocking_flags('both', procedure_ready=True)
        self.assertEqual(flags, [])
        self.assertFalse(blocking.has_hard_block(flags))

    def test_bao_xong_thu_tuc_khong_bien_thanh_co_mem(self):
        # Cờ mềm mang nghĩa "xe công ty không phải chạy". Hạ cờ thủ tục xuống mềm thay vì
        # bỏ hẳn thì đơn biến mất khỏi mọi chuyến — hỏng theo chiều ngược lại.
        flags = blocking.blocking_flags('customs', procedure_ready=True)
        self.assertEqual([flag for flag in flags if not flag['hard']], [])

    def test_bao_xong_thu_tuc_khong_dung_toi_kenh_giao(self):
        flags = blocking.blocking_flags('customs', 'express', procedure_ready=True)
        self.assertEqual([flag['code'] for flag in flags], ['express'])
        self.assertFalse(blocking.has_hard_block(flags))


class TestKenhGiao(unittest.TestCase):

    def test_cpn_la_co_mem(self):
        flags = blocking.blocking_flags(None, 'express')
        self.assertEqual(len(flags), 1)
        self.assertFalse(flags[0]['hard'])

    def test_khong_vuong_gi_thi_rong(self):
        self.assertEqual(blocking.blocking_flags('none', 'company'), [])


if __name__ == '__main__':
    unittest.main()
