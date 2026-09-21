"""Test bộ dò trùng địa chỉ / địa điểm. Chạy được KHÔNG cần Odoo — xem lệnh ở đầu
``test_vtracking_route.py``.

Dữ liệu lấy từ đơn thật kho Bến Cam ngày 21/09/2026. Sai theo hướng GỘP NHẦM nguy hiểm hơn
bỏ sót: gộp nhầm là hai khách thành một điểm, xe tới nhầm chỗ.
"""

import unittest

try:
    from . import standalone
except ImportError:  # chạy bằng python trần: thư mục tests là gốc
    import standalone

dedup = standalone.load_tool('vtracking_dedup')

# Cùng một lô, viết theo tên hành chính trước và sau sáp nhập 2025.
TOPBAND_OLD = 'Lô D, KCN Lộc An - Bình Sơn, Xã Long Thành, Tỉnh Đồng Nai, Việt Nam'
TOPBAND_NEW = 'Lô D, KCN Lộc An - Bình Sơn, Phường Long Thành, Thành phố Đồng Nai'
# Lô khác trong cùng KCN.
BAO_TIN = 'Lô N, Khu công nghiệp Lộc An - Bình Sơn, Phường Long Thành, Thành phố Đồng Nai'
# Hai công ty khác nhau, geocoder trả cùng một tâm KCN.
KCN_CENTER = (10.7300, 106.9400)
JUNGWOO = 'KCN Dệt May Nhơn Trạch, Xã Nhơn Trạch, Tỉnh Đồng Nai, Việt Nam'
VACPRO = 'Đường 25B, KCN Nhơn Trạch 1, Xã Nhơn Trạch, Đồng Nai, Việt Nam'


def addr(row_id, raw, point=None, state='pending_review', hits=0):
    return {'id': row_id, 'raw_address': raw, 'point': point, 'geo_state': state,
            'hit_count': hits}


class TestDiaChi(unittest.TestCase):

    def test_ten_hanh_chinh_cu_moi_la_mot(self):
        groups = dedup.address_duplicate_groups([addr(1, TOPBAND_OLD), addr(2, TOPBAND_NEW)])
        self.assertEqual([group['ids'] for group in groups], [[1, 2]])

    def test_lo_khac_cung_kcn_khong_trung(self):
        groups = dedup.address_duplicate_groups([addr(1, TOPBAND_NEW), addr(2, BAO_TIN)])
        self.assertEqual(groups, [])

    def test_mot_ben_co_so_lo_mot_ben_khong_thi_khong_gop(self):
        # Không biết "KCN Lộc An - Bình Sơn" trơn là lô nào -> không gộp vào Lô D.
        groups = dedup.address_duplicate_groups([
            addr(1, TOPBAND_NEW),
            addr(2, 'KCN Lộc An - Bình Sơn, Phường Long Thành, Thành phố Đồng Nai'),
        ])
        self.assertEqual(groups, [])

    def test_cung_toa_do_tam_kcn_khong_du_de_gop(self):
        groups = dedup.address_duplicate_groups([
            addr(1, JUNGWOO, KCN_CENTER), addr(2, VACPRO, KCN_CENTER),
        ])
        self.assertEqual(groups, [])

    def test_chu_giong_nhung_cach_xa_thi_khong_trung(self):
        groups = dedup.address_duplicate_groups([
            addr(1, TOPBAND_OLD, (10.80, 107.00)), addr(2, TOPBAND_NEW, (10.90, 107.10)),
        ])
        self.assertEqual(groups, [])

    def test_giu_ban_toa_do_dang_tin_nhat(self):
        groups = dedup.address_duplicate_groups([
            addr(1, TOPBAND_OLD, state='pending_review', hits=30),
            addr(2, TOPBAND_NEW, state='manual', hits=1),
        ])
        self.assertEqual(groups[0]['keep_id'], 2)


def place(row_id, name_key, root=None, point=None, profile=False, warehouse=False,
          state='confirmed'):
    return {'id': row_id, 'name_key': name_key, 'root_partner_id': root, 'point': point,
            'geo_state': state, 'has_profile': profile, 'has_warehouse': warehouse}


class TestDiaDiem(unittest.TestCase):

    def test_cung_phap_nhan_goc(self):
        groups = dedup.place_duplicate_groups([place(1, 'topbandsmart', 684),
                                               place(2, 'topbanddongnai', 684)])
        self.assertEqual(groups[0]['reasons'], ['same_customer'])

    def test_giu_ban_co_thoi_quen_khach(self):
        groups = dedup.place_duplicate_groups([place(1, 'nox', 5),
                                               place(2, 'noxasean', 5, profile=True)])
        self.assertEqual(groups[0]['keep_id'], 2)

    def test_gan_nhau_ma_ten_khac_han_khong_trung(self):
        groups = dedup.place_duplicate_groups([
            place(1, 'jungwoovina', point=KCN_CENTER), place(2, 'vacpro', point=KCN_CENTER),
        ])
        self.assertEqual(groups, [])

    def test_cung_cho_ten_bao_nhau(self):
        groups = dedup.place_duplicate_groups([
            place(1, 'noxasean', point=KCN_CENTER), place(2, 'nox', point=KCN_CENTER),
        ])
        self.assertEqual(groups[0]['reasons'], ['same_spot'])


if __name__ == '__main__':
    unittest.main()
