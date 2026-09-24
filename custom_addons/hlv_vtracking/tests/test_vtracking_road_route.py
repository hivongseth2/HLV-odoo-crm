"""Test phần THUẦN của lộ trình đường thật: dựng yêu cầu, nhận diện lộ trình đã đổi, đọc
kết quả Google trả về. Chạy được KHÔNG cần Odoo và KHÔNG gọi mạng:

    python -m unittest discover -s custom_addons/hlv_vtracking/tests -t custom_addons/hlv_vtracking/tests

Phần gọi HTTP (``services/google_routes.py``) không test ở đây — nó chỉ còn việc gửi đi và
đổi lỗi thành câu tiếng Việt; mọi thứ dễ sai (thứ tự điểm, ngưỡng số điểm, đọc '1234s',
quyết định khi nào phải gọi lại) đã được kéo hết về ``tools/`` để test được chỗ này.
"""

import unittest

try:
    from . import standalone
except ImportError:  # chạy bằng python trần: thư mục tests là gốc
    import standalone

road = standalone.load_tool('vtracking_road_route')

KHO = (10.7489944, 106.9241992)
NOX = (10.7010, 106.9020)
CAP_DIEN = (10.7300, 106.9400)


class TestRoutePoints(unittest.TestCase):

    def test_kho_dung_dau_roi_den_cac_diem(self):
        points = road.route_points(KHO, [NOX, CAP_DIEN])
        self.assertEqual(points, [KHO, NOX, CAP_DIEN])

    def test_diem_thieu_toa_do_bi_bo_qua(self):
        # Điểm chưa tra được toạ độ không gọi API được; phần tính chim bay cũng bỏ qua
        # chúng (missing_coords_count), hai bên phải bỏ giống nhau.
        points = road.route_points(KHO, [NOX, None, CAP_DIEN])
        self.assertEqual(points, [KHO, NOX, CAP_DIEN])

    def test_khong_co_kho_thi_bat_dau_tu_diem_dau(self):
        points = road.route_points(None, [NOX, CAP_DIEN])
        self.assertEqual(points, [NOX, CAP_DIEN])


class TestRouteSignature(unittest.TestCase):

    def test_doi_thu_tu_ghe_la_doi_dau(self):
        a = road.route_signature([KHO, NOX, CAP_DIEN])
        b = road.route_signature([KHO, CAP_DIEN, NOX])
        self.assertNotEqual(a, b)

    def test_them_diem_la_doi_dau(self):
        a = road.route_signature([KHO, NOX])
        b = road.route_signature([KHO, NOX, CAP_DIEN])
        self.assertNotEqual(a, b)

    def test_lech_duoi_met_thi_van_la_mot_lo_trinh(self):
        # Tra lại toạ độ cùng một điểm có thể lệch ở chữ số cuối. Lệch cỡ centimet thì
        # đường đi không khác gì — gọi lại API cho việc đó là tốn tiền vô ích.
        nhich = (NOX[0] + 0.000001, NOX[1])
        self.assertEqual(
            road.route_signature([KHO, NOX]),
            road.route_signature([KHO, nhich]),
        )


class TestComputeRoutesBody(unittest.TestCase):

    def test_diem_dau_la_origin_diem_cuoi_la_destination(self):
        body = road.compute_routes_body([KHO, NOX, CAP_DIEN])
        self.assertEqual(body['origin']['location']['latLng']['latitude'], KHO[0])
        self.assertEqual(body['destination']['location']['latLng']['latitude'], CAP_DIEN[0])
        self.assertEqual(len(body['intermediates']), 1)
        self.assertEqual(body['intermediates'][0]['location']['latLng']['latitude'], NOX[0])

    def test_khong_cho_google_xep_lai_thu_tu(self):
        # Thứ tự ghé đã được cân theo cụm tuyến, thủ tục và thói quen khách. Để Google xếp
        # lại theo km ngắn nhất là phá bỏ toàn bộ phần lý giải đó.
        body = road.compute_routes_body([KHO, NOX, CAP_DIEN])
        self.assertFalse(body['optimizeWaypointOrder'])

    def test_khong_dung_ban_co_traffic(self):
        # Số này được LƯU LẠI và đem so giữa các chuyến, nên phải ổn định.
        body = road.compute_routes_body([KHO, NOX])
        self.assertEqual(body['routingPreference'], 'TRAFFIC_UNAWARE')

    def test_duoi_hai_diem_thi_bao_loi(self):
        with self.assertRaises(road.RoadRouteInputError):
            road.compute_routes_body([KHO])

    def test_qua_nhieu_diem_thi_bao_loi_chu_khong_cat_bot(self):
        # Cắt bớt điểm cho vừa hạn mức là vẽ ra lộ trình thiếu điểm mà người xem không biết.
        points = [KHO] + [NOX] * (road.MAX_INTERMEDIATES + 1) + [CAP_DIEN]
        with self.assertRaises(road.RoadRouteInputError):
            road.compute_routes_body(points)


class TestParseResponse(unittest.TestCase):

    def test_doc_km_phut_va_duong_ve(self):
        result = road.parse_route_response({'routes': [{
            'distanceMeters': 18470,
            'duration': '1980s',
            'polyline': {'encodedPolyline': 'abcd'},
        }]})
        self.assertEqual(result['distance_km'], 18.5)
        self.assertEqual(result['duration_minutes'], 33)
        self.assertEqual(result['polyline'], 'abcd')

    def test_khong_tim_duoc_duong_tra_none(self):
        # Kết quả hợp lệ của API, không phải lỗi: VD điểm giao bị geocode ra giữa ruộng.
        self.assertIsNone(road.parse_route_response({'routes': []}))
        self.assertIsNone(road.parse_route_response({}))

    def test_thoi_luong_dang_chuoi_co_hau_to_s(self):
        self.assertEqual(road.parse_duration_seconds('1234s'), 1234)
        self.assertEqual(road.parse_duration_seconds('1234'), 1234)
        self.assertEqual(road.parse_duration_seconds(''), 0)
        self.assertEqual(road.parse_duration_seconds(None), 0)
        self.assertEqual(road.parse_duration_seconds('không phải số'), 0)


if __name__ == '__main__':
    unittest.main()
