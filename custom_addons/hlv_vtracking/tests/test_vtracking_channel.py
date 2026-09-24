"""Test phần đọc kênh giao. Chạy KHÔNG cần Odoo — xem lệnh ở đầu ``test_vtracking_route.py``.

Đọc sai ở đây có hai hậu quả: đơn khách tự lấy bị xếp lên xe (thừa một điểm dừng, tài xế
tới nơi không ai chờ), hoặc ngược lại đơn phải giao bị loại khỏi kế hoạch.
"""

import unittest

try:
    from . import standalone
except ImportError:  # chạy bằng python trần: thư mục tests là gốc
    import standalone

channel = standalone.load_tool('vtracking_channel')


class TestDauHieuRo(unittest.TestCase):
    """``channel_hint`` — dùng cho ô KHÔNG phải ô hình thức giao hàng."""

    def test_doc_duoc_cpn_trong_o_nguon(self):
        self.assertEqual(channel.channel_hint('CPN'), 'express')

    def test_doc_duoc_grab(self):
        self.assertEqual(channel.channel_hint('BOOK GRAB GIAO KHÁCH'), 'grab')

    def test_doc_duoc_khach_ghe_lay(self):
        self.assertEqual(channel.channel_hint('KHÁCH GHÉ LẤY'), 'pickup')

    def test_ten_khach_thi_khong_doan(self):
        # Ô "Nguồn" phần lớn là tên khách. Không khớp luật nào nghĩa là KHÔNG BIẾT — trả
        # 'other' ở đây thì mọi đơn đều thành "Khác — đọc ghi chú" và cờ mất hết giá trị.
        self.assertIsNone(
            channel.channel_hint('Đơn hàng bán cho CÔNG TY TNHH SUMMIT POLYMERS VIETNAM'))

    def test_o_trong_thi_khong_doan(self):
        self.assertIsNone(channel.channel_hint(''))
        self.assertIsNone(channel.channel_hint(None))


class TestOHinhThucGiaoHang(unittest.TestCase):
    """``delivery_channel`` — ô sale gõ tay, giữ nguyên nghĩa cũ."""

    def test_o_trong_tra_none(self):
        self.assertIsNone(channel.delivery_channel('   '))

    def test_co_chu_ma_khong_khop_thi_la_other(self):
        self.assertEqual(channel.delivery_channel('giao trước 10h sáng'), 'other')

    def test_khop_luat_thi_ra_ma(self):
        self.assertEqual(channel.delivery_channel('Gửi chuyển phát nhanh'), 'express')

    def test_khach_book_xe_lay_hang_la_tu_lay(self):
        self.assertEqual(channel.delivery_channel('khách book xe lấy hàng'), 'pickup')


class TestCanXeCongTy(unittest.TestCase):

    def test_khong_biet_thi_coi_nhu_can_xe(self):
        self.assertTrue(channel.needs_company_truck(None))

    def test_tu_lay_thi_khong_can_xe(self):
        self.assertFalse(channel.needs_company_truck('pickup'))

    def test_other_van_can_xe_vi_chua_ai_doc(self):
        self.assertTrue(channel.needs_company_truck('other'))


if __name__ == '__main__':
    unittest.main()
