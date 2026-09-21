"""Test công thức quãng đường / thời gian của kế hoạch. Chạy được KHÔNG cần Odoo:

    python -m unittest discover -s custom_addons/hlv_vtracking/tests -t custom_addons/hlv_vtracking/tests

(``-t`` phải trỏ vào CHÍNH thư mục tests: trỏ ra gốc repo thì unittest import cả addon,
kéo theo ``import odoo`` và chết trước khi chạy được test nào.)

``tools/vtracking_route`` là nơi DUY NHẤT tính giờ tới cho màn hình, API cho AI và đối
chiếu kế hoạch với thực tế. Sai ở đây là sai mọi con số của module.
"""

import importlib.util
import os
import sys
import types
import unittest

try:
    from odoo.addons.hlv_vtracking.tools import vtracking_route as route
except ImportError:  # chạy bằng python trần, ngoài Odoo
    HERE = os.path.dirname(os.path.abspath(__file__))
    ADDONS = os.path.abspath(os.path.join(HERE, '..', '..'))

    def _load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    # vtracking_route import haversine qua đường dẫn addon của Odoo — dựng đúng đường dẫn
    # đó từ file thật, không viết lại hàm.
    for package in ('odoo', 'odoo.addons', 'odoo.addons.hlv_geo_utils',
                    'odoo.addons.hlv_geo_utils.tools'):
        sys.modules.setdefault(package, types.ModuleType(package))
    _load('odoo.addons.hlv_geo_utils.tools.geo_distance',
          os.path.join(ADDONS, 'hlv_geo_utils', 'tools', 'geo_distance.py'))
    route = _load('vtracking_route', os.path.join(ADDONS, 'hlv_vtracking', 'tools', 'vtracking_route.py'))


KHO = (10.7489944, 106.9241992)
NOX = (10.7010, 106.9020)          # KCN Nhơn Trạch 6
NOX_SAN_BEN = (10.70112, 106.9020)  # cùng cổng, geocode lệch ~13 m
NOX_XUONG_KHAC = (10.70190, 106.9020)  # ~100 m — xưởng khác trong cùng KCN
CAP_DIEN = (10.7300, 106.9400)     # KCN Nhơn Trạch II
TOPBAND = (10.8000, 107.0000)      # KCN Lộc An – Bình Sơn

NHON_TRACH = {'zone_id': 1, 'hub_to_first_minutes': 40, 'median_leg_minutes': 13,
              'return_minutes': 25}
LONG_THANH = {'zone_id': 2, 'hub_to_first_minutes': 57, 'median_leg_minutes': 15,
              'return_minutes': 30}


def params(zone=None):
    return route.route_params(35.0, 10, 1.3, zone=zone)


class TestCungMotDiem(unittest.TestCase):
    """Đơn vị tải của chuyến là ĐIỂM, không phải ĐƠN."""

    def test_ba_don_cung_diem_chi_tinh_mot_lan(self):
        legs = route.estimate_legs(KHO, [NOX, NOX, NOX], params(NHON_TRACH))
        self.assertEqual([leg['arrive_offset_minutes'] for leg in legs], [40, 40, 40])
        self.assertEqual([leg['same_point'] for leg in legs], [False, True, True])
        self.assertEqual(legs[1]['leg_km'], 0.0)

    def test_lech_vai_chuc_met_van_la_mot_diem(self):
        legs = route.estimate_legs(KHO, [NOX, NOX_SAN_BEN], params(NHON_TRACH))
        self.assertTrue(legs[1]['same_point'])

    def test_cach_tram_met_la_hai_diem(self):
        legs = route.estimate_legs(KHO, [NOX, NOX_XUONG_KHAC], params(NHON_TRACH))
        self.assertFalse(legs[1]['same_point'])

    def test_hai_nha_may_khac_nhau_la_hai_diem(self):
        legs = route.estimate_legs(KHO, [NOX, CAP_DIEN], params(NHON_TRACH))
        self.assertFalse(legs[1]['same_point'])
        self.assertEqual(legs[1]['arrive_offset_minutes'], 40 + 13)

    def test_don_lap_khong_cong_phut_lau_hon_lan_nua(self):
        # Khách khai đứng lâu hơn 20': ba đơn cùng chỗ vẫn chỉ đứng thêm 20' một lần.
        result = route.estimate_route(KHO, [NOX, NOX, NOX], params(NHON_TRACH), [20, 20, 20])
        self.assertEqual(result['service_minutes'], 20)

    def test_thieu_toa_do_thi_so_theo_khoa_dia_chi(self):
        legs = route.estimate_legs(
            KHO, [None, None], params(NHON_TRACH), stop_keys=['addr-7', 'addr-7'],
        )
        self.assertTrue(legs[1]['same_point'])

    def test_thieu_toa_do_va_khong_co_khoa_thi_coi_la_khac(self):
        legs = route.estimate_legs(KHO, [None, None], params(NHON_TRACH))
        self.assertFalse(legs[1]['same_point'])

    def test_tinh_theo_km_cung_khong_cong_thoi_gian_dung_lan_hai(self):
        result = route.estimate_route(KHO, [NOX, NOX], params())
        self.assertEqual(result['service_minutes'], 10)


class TestNhieuCum(unittest.TestCase):
    """Chuyến gom hai cụm: mỗi điểm theo định mức cụm của chính nó."""

    def test_chang_trong_cum_sau_theo_nhip_cum_sau(self):
        stops = [NOX, CAP_DIEN, TOPBAND, (10.8100, 107.0100)]
        zones = [NHON_TRACH, NHON_TRACH, LONG_THANH, LONG_THANH]
        legs = route.estimate_legs(KHO, stops, params(NHON_TRACH), stop_zones=zones)
        # Chặng thứ tư nằm trọn trong Long Thành -> 15', không phải 13' của Nhơn Trạch.
        self.assertEqual(legs[3]['leg_minutes'], 15)

    def test_chang_vuot_cum_tinh_theo_km_cong_thoi_gian_dung(self):
        zones = [NHON_TRACH, LONG_THANH]
        legs = route.estimate_legs(KHO, [NOX, TOPBAND], params(NHON_TRACH), stop_zones=zones)
        drive = round(legs[1]['leg_km'] / 35.0 * 60)
        self.assertEqual(legs[1]['leg_minutes'], drive + 10)

    def test_vuot_cum_khong_do_duoc_km_thi_lui_ve_nhip_cum_dich(self):
        zones = [NHON_TRACH, LONG_THANH]
        legs = route.estimate_legs(KHO, [NOX, None], params(NHON_TRACH), stop_zones=zones)
        self.assertEqual(legs[1]['leg_minutes'], 15)

    def test_chang_ve_theo_cum_diem_cuoi(self):
        zones = [NHON_TRACH, LONG_THANH]
        result = route.estimate_route(KHO, [NOX, TOPBAND], params(NHON_TRACH), stop_zones=zones)
        self.assertEqual(result['return_minutes'], 30)

    def test_chang_dau_theo_cum_diem_dau(self):
        legs = route.estimate_legs(KHO, [TOPBAND], params(NHON_TRACH), stop_zones=[LONG_THANH])
        self.assertEqual(legs[0]['leg_minutes'], 57)


class TestGiuCachTinhCu(unittest.TestCase):
    """Bên gọi chưa truyền cụm từng điểm phải ra ĐÚNG con số như trước khi sửa."""

    def test_mot_cum_khong_truyen_stop_zones(self):
        result = route.estimate_route(KHO, [NOX, CAP_DIEN], params(NHON_TRACH))
        self.assertEqual(result['drive_minutes'], 40 + 13)
        self.assertEqual(result['service_minutes'], 0)
        self.assertEqual(result['return_minutes'], 25)
        self.assertEqual(result['total_minutes'], 40 + 13 + 25)

    def test_khong_cum_tinh_theo_km(self):
        result = route.estimate_route(KHO, [NOX, CAP_DIEN], params())
        self.assertEqual(result['service_minutes'], 20)
        self.assertEqual(result['return_minutes'], 0)

    def test_khong_diem_xuat_phat_thi_khong_co_chang_dau(self):
        legs = route.estimate_legs(None, [NOX, CAP_DIEN], params(NHON_TRACH))
        self.assertIsNone(legs[0]['leg_minutes'])
        self.assertEqual(legs[1]['leg_minutes'], 13)

    def test_lo_trinh_rong(self):
        result = route.estimate_route(KHO, [], params(NHON_TRACH))
        self.assertEqual(result['total_minutes'], 0)
        self.assertEqual(result['legs'], [])


class TestChuyenThat2109(unittest.TestCase):
    """Kế hoạch #2 ngày 21/09: 8 đơn, 5 điểm — bug cũ cộng 13' cho mỗi ĐƠN."""

    def test_nam_diem_tam_don(self):
        stops = [(10.735, 106.905), CAP_DIEN, NOX, NOX, NOX, TOPBAND, TOPBAND, (10.785, 106.960)]
        zones = [NHON_TRACH] * 5 + [LONG_THANH] * 3
        legs = route.estimate_legs(KHO, stops, params(NHON_TRACH), stop_zones=zones)
        self.assertEqual(sum(1 for leg in legs if not leg['same_point']), 5)
        # NOX: ba đơn tới cùng một lúc
        self.assertEqual(len({leg['arrive_offset_minutes'] for leg in legs[2:5]}), 1)


if __name__ == '__main__':
    unittest.main()
