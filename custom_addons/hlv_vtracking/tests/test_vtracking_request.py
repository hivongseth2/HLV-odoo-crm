"""Test luật trạng thái phiếu yêu cầu gửi AI. Chạy KHÔNG cần Odoo — xem lệnh ở đầu
``test_vtracking_route.py``.

Sai ở đây nghĩa là hai worker cùng trả lời một phiếu, hoặc phiếu đã xử lý xong vẫn bị làm
lại — cả hai đều tạo ra câu trả lời chồng nhau gửi cho người bán hàng.
"""

import unittest
from datetime import datetime, timedelta

try:
    from . import standalone
except ImportError:  # chạy bằng python trần: thư mục tests là gốc
    import standalone

request = standalone.load_tool('vtracking_request')

NOW = datetime(2026, 9, 21, 13, 0)


class TestNhanViec(unittest.TestCase):

    def test_chi_phieu_dang_cho_moi_nhan_duoc(self):
        self.assertTrue(request.claimable('pending'))

    def test_phieu_may_khac_dang_lam_thi_khong(self):
        for state in ('processing', 'answered', 'done', 'rejected', 'failed', 'cancelled'):
            self.assertFalse(request.claimable(state), state)


class TestSauKhiTraLoi(unittest.TestCase):

    def test_da_sua_ke_hoach_thi_xong(self):
        self.assertEqual(request.state_after_answer(True), 'done')

    def test_chi_de_xuat_thi_cho_nguoi_duyet(self):
        self.assertEqual(request.state_after_answer(False), 'answered')


class TestThoiGianCho(unittest.TestCase):

    def test_dem_toi_luc_nhan_viec(self):
        created = NOW - timedelta(minutes=30)
        claimed = NOW - timedelta(minutes=28)
        self.assertEqual(request.waiting_minutes(created, claimed, NOW), 2)

    def test_chua_ai_nhan_thi_dem_toi_bay_gio(self):
        self.assertEqual(request.waiting_minutes(NOW - timedelta(minutes=7), None, NOW), 7)

    def test_thieu_moc_tao_thi_khong_doan(self):
        self.assertIsNone(request.waiting_minutes(None, None, NOW))

    def test_cho_qua_nguong_la_worker_dang_tat(self):
        self.assertTrue(request.is_stale('pending', 10, 10))
        self.assertFalse(request.is_stale('pending', 9, 10))

    def test_phieu_da_tra_loi_nam_lau_khong_phai_loi_may(self):
        self.assertFalse(request.is_stale('answered', 500, 10))

    def test_chua_do_duoc_thi_khong_canh_bao(self):
        self.assertFalse(request.is_stale('pending', None, 10))
