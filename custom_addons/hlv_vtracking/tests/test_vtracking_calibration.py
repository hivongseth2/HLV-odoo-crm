"""Test phần học lại định mức cụm từ chuyến đã chạy. Chạy được KHÔNG cần Odoo — xem
lệnh ở đầu ``test_vtracking_route.py``.

Sai ở đây nghĩa là đề xuất sai, rồi người điều phối bấm áp dụng và mọi kế hoạch sau đó lệch
theo — nên từng loại mẫu đều có test riêng.
"""

import unittest
from datetime import datetime, timedelta

try:
    from . import standalone
except ImportError:  # chạy bằng python trần: thư mục tests là gốc
    import standalone

calibration = standalone.load_tool('vtracking_calibration')

NT, LT = 1, 2
START = datetime(2026, 9, 21, 13, 0)
A = (10.7300, 106.9400)
B = (10.7010, 106.9020)
C = (10.7200, 106.9100)
D = (10.8000, 107.0000)


def stop(minutes, zone, point, key=None):
    return {'delivered_at': START + timedelta(minutes=minutes), 'zone_id': zone,
            'point': point, 'key': key}


class TestMauMotChuyen(unittest.TestCase):

    def test_ba_loai_mau(self):
        stops = [stop(40, NT, A), stop(55, NT, B), stop(70, NT, C)]
        samples = calibration.trip_samples(START, True, stops, START + timedelta(minutes=95))
        self.assertEqual(samples, [
            ('hub', NT, 40), ('leg', NT, 15), ('leg', NT, 15), ('return', NT, 25),
        ])

    def test_moc_xuat_phat_khong_phai_luc_quet_thi_khong_lay_mau_hub(self):
        # actual_start_at lùi về lúc giao xong điểm đầu -> chặng đầu ra 0, vô nghĩa.
        samples = calibration.trip_samples(START, False, [stop(40, NT, A), stop(55, NT, B)])
        self.assertEqual([kind for kind, _, _ in samples], ['leg'])

    def test_nhieu_don_mot_diem_khong_sinh_mau_0_phut(self):
        stops = [stop(40, NT, A), stop(42, NT, A), stop(43, NT, A), stop(58, NT, B)]
        samples = calibration.trip_samples(START, True, stops)
        # "Giao xong điểm A" là lúc xong ĐƠN CUỐI ở A (phút 43) — lúc xe thật sự rời đi. Dùng
        # cùng một mốc cho cả mẫu hub lẫn chặng A -> B, khớp cách kế hoạch tính giờ.
        self.assertEqual(samples, [('hub', NT, 43), ('leg', NT, 15)])

    def test_chang_vuot_cum_khong_thuoc_cum_nao(self):
        stops = [stop(40, NT, A), stop(75, LT, D)]
        samples = calibration.trip_samples(START, True, stops, START + timedelta(minutes=110))
        self.assertEqual(samples, [('hub', NT, 40), ('return', LT, 35)])

    def test_sap_theo_gio_giao_that_khong_theo_thu_tu_ke_hoach(self):
        stops = [stop(70, NT, C), stop(40, NT, A), stop(55, NT, B)]
        samples = calibration.trip_samples(START, True, stops)
        self.assertEqual(samples[0], ('hub', NT, 40))

    def test_bo_mau_hong(self):
        # Hai phiếu bấm xong cùng một phút ở hai nơi, và một phiếu bấm bù cuối ngày.
        stops = [stop(40, NT, A), stop(40, NT, B), stop(400, NT, C)]
        samples = calibration.trip_samples(START, True, stops)
        self.assertEqual(samples, [('hub', NT, 40)])

    def test_diem_chua_co_cum_khong_lay_mau(self):
        samples = calibration.trip_samples(START, True, [stop(40, None, A), stop(55, None, B)])
        self.assertEqual(samples, [])

    def test_chuyen_rong(self):
        self.assertEqual(calibration.trip_samples(START, True, []), [])


class TestDeXuat(unittest.TestCase):
    CURRENT = {NT: {'hub': 40, 'leg': 13, 'return': 25}}

    def test_du_mau_va_lech_thi_de_xuat(self):
        samples = [('leg', NT, 16)] * 12
        result = calibration.suggestions(samples, self.CURRENT)
        self.assertEqual(result[NT]['leg']['suggest'], 16)
        self.assertEqual(result[NT]['leg']['count'], 12)

    def test_chua_du_mau_thi_chi_bao_so_do(self):
        result = calibration.suggestions([('leg', NT, 16)] * 5, self.CURRENT)
        self.assertIsNone(result[NT]['leg']['suggest'])
        self.assertEqual(result[NT]['leg']['median'], 16)

    def test_lech_it_thi_khong_de_xuat(self):
        result = calibration.suggestions([('leg', NT, 14)] * 20, self.CURRENT)
        self.assertIsNone(result[NT]['leg']['suggest'])

    def test_dung_trung_vi_khong_dung_trung_binh(self):
        # Một chuyến kẹt xe 200 phút không được kéo định mức lên.
        samples = [('leg', NT, 16)] * 11 + [('leg', NT, 200)]
        result = calibration.suggestions(samples, self.CURRENT)
        self.assertEqual(result[NT]['leg']['suggest'], 16)

    def test_trung_vi_so_chan(self):
        self.assertEqual(calibration.median([10, 20]), 15)
        self.assertIsNone(calibration.median([]))


if __name__ == '__main__':
    unittest.main()
