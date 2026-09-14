"""Test cho công thức thời gian. Chạy được KHÔNG cần Odoo:

    python -m unittest discover -s custom_addons/hlv_purchase_pickup/tests -t .

``pickup_metrics`` cố tình không đụng ``self.env`` chính là để test được như thế này — đây
là nơi duy nhất chứa công thức, sai ở đây là sai toàn bộ số liệu của module.
"""

import os
import sys
import unittest
from datetime import datetime

try:
    from odoo.addons.hlv_purchase_pickup.services import pickup_metrics
except ImportError:  # chạy bằng python trần, ngoài Odoo
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'services'))
    import pickup_metrics


def at(hour, minute):
    return datetime(2026, 9, 14, hour, minute)


def stop(key, sequence, arrived=None, done=None):
    return {'key': key, 'sequence': sequence, 'arrived_at': arrived, 'done_at': done}


class TestRunTimings(unittest.TestCase):

    def test_tach_di_chuyen_khoi_nhan_hang(self):
        result = pickup_metrics.compute_run_timings(
            at(7, 0), at(11, 0),
            [
                stop('a', 10, at(7, 40), at(8, 0)),
                stop('b', 20, at(8, 30), at(8, 50)),
            ],
        )
        self.assertEqual(result['stops']['a']['travel_minutes'], 40)
        self.assertEqual(result['stops']['a']['service_minutes'], 20)
        # Chặng b tính từ lúc RỜI a (8:00), không phải từ lúc tới a.
        self.assertEqual(result['stops']['b']['travel_minutes'], 30)
        self.assertEqual(result['stops']['b']['service_minutes'], 20)
        self.assertEqual(result['total_travel_minutes'], 70)
        self.assertEqual(result['total_service_minutes'], 40)
        self.assertEqual(result['total_minutes'], 240)
        self.assertEqual(result['idle_minutes'], 130)

    def test_di_dao_thu_tu_van_ra_so_duong(self):
        """Đi điểm số 2 trước điểm số 1 — tính theo thứ tự kế hoạch sẽ ra số phút âm."""
        result = pickup_metrics.compute_run_timings(
            at(7, 0), None,
            [
                stop('xa', 10, at(8, 30), at(8, 45)),
                stop('gan', 20, at(7, 30), at(7, 50)),
            ],
        )
        self.assertEqual(result['order'], ['gan', 'xa'])
        self.assertEqual(result['stops']['gan']['travel_minutes'], 30)
        self.assertEqual(result['stops']['xa']['travel_minutes'], 40)
        self.assertFalse(result['stops']['xa']['chain_broken'])

    def test_diem_bi_bo_qua_khong_lam_gay_chuoi(self):
        result = pickup_metrics.compute_run_timings(
            at(7, 0), None,
            [
                stop('a', 10, at(7, 30), at(7, 45)),
                stop('bo_qua', 20),
                stop('c', 30, at(8, 15), at(8, 30)),
            ],
        )
        # c tính từ lúc rời a, điểm bỏ qua bị nhảy qua.
        self.assertEqual(result['stops']['c']['travel_minutes'], 30)
        self.assertIsNone(result['stops']['bo_qua']['travel_minutes'])
        self.assertFalse(result['stops']['bo_qua']['chain_broken'])

    def test_quen_bam_da_toi(self):
        """Model ghi arrived_at = done_at khi quên bấm — thời gian nhận ra 0, không ra âm."""
        result = pickup_metrics.compute_run_timings(
            at(7, 0), None, [stop('a', 10, at(7, 40), at(7, 40))],
        )
        self.assertEqual(result['stops']['a']['travel_minutes'], 40)
        self.assertEqual(result['stops']['a']['service_minutes'], 0)

    def test_moc_nguoc_thi_bao_gay_chu_khong_tra_0(self):
        result = pickup_metrics.compute_run_timings(
            at(9, 0), None, [stop('a', 10, at(7, 40), at(8, 0))],
        )
        self.assertIsNone(result['stops']['a']['travel_minutes'])
        self.assertTrue(result['stops']['a']['chain_broken'])
        self.assertEqual(result['total_travel_minutes'], 0)

    def test_chua_xuat_phat(self):
        result = pickup_metrics.compute_run_timings(None, None, [stop('a', 10)])
        self.assertIsNone(result['stops']['a']['travel_minutes'])
        self.assertIsNone(result['total_minutes'])
        self.assertIsNone(result['idle_minutes'])

    def test_chuyen_rong(self):
        result = pickup_metrics.compute_run_timings(at(7, 0), None, [])
        self.assertEqual(result['order'], [])
        self.assertEqual(result['total_travel_minutes'], 0)


class TestClock(unittest.TestCase):

    def test_doc_iso_tu_trinh_duyet(self):
        parsed = pickup_metrics.parse_iso_datetime('2026-09-14T08:12:33.000Z')
        self.assertEqual(parsed, datetime(2026, 9, 14, 8, 12, 33))
        self.assertIsNone(parsed.tzinfo)

    def test_iso_hong_tra_none(self):
        self.assertIsNone(pickup_metrics.parse_iso_datetime('hôm qua'))
        self.assertIsNone(pickup_metrics.parse_iso_datetime(''))

    def test_uu_tien_gio_bam_khi_gui_muon(self):
        """Mất sóng 20 phút rồi mới gửi được: mốc phải là lúc bấm, không phải lúc gửi."""
        press = at(8, 12)
        received = at(8, 32)
        self.assertEqual(pickup_metrics.pick_event_time(press, received), press)

    def test_bo_gio_may_khi_dong_ho_sai_han(self):
        press = datetime(2026, 9, 11, 8, 12)
        now = at(8, 12)
        self.assertEqual(pickup_metrics.pick_event_time(press, now), now)

    def test_khong_co_gio_bam_thi_dung_gio_may_chu(self):
        now = at(8, 12)
        self.assertEqual(pickup_metrics.pick_event_time(None, now), now)


class TestStats(unittest.TestCase):

    def test_trung_vi_bo_qua_none(self):
        self.assertEqual(pickup_metrics.median([10, None, 20, 30]), 20.0)
        self.assertEqual(pickup_metrics.median([10, 20]), 15.0)
        self.assertIsNone(pickup_metrics.median([]))

    def test_trung_vi_khong_bi_keo_boi_mot_lan_cho_lau(self):
        """Lý do dùng trung vị chứ không dùng trung bình cho định mức."""
        values = [15, 18, 20, 22, 180]
        self.assertEqual(pickup_metrics.median(values), 20.0)
        self.assertEqual(pickup_metrics.average(values), 51.0)


if __name__ == '__main__':
    unittest.main()
