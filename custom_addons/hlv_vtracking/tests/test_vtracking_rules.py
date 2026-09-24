"""Test phần đọc file luật khách. Chạy KHÔNG cần Odoo — xem lệnh ở đầu ``test_vtracking_route.py``.

Đọc sai ở đây nghĩa là ghi sai thói quen của khách thật: một khách cần thông quan mà mất
cờ là xe tới cổng rồi phải chở hàng về.
"""

import unittest

try:
    from . import standalone
except ImportError:  # chạy bằng python trần: thư mục tests là gốc
    import standalone

rules = standalone.load_tool('vtracking_rules')


class TestChuanHoaTen(unittest.TestCase):

    def test_bo_tien_to_phap_nhan(self):
        self.assertEqual(rules.normalize('CÔNG TY TNHH Cáp điện & Hệ thống LS Việt Nam'),
                         'cap dien he thong ls viet nam')

    def test_bo_tien_to_dai_truoc_tien_to_ngan(self):
        self.assertEqual(rules.normalize('Công ty trách nhiệm hữu hạn một thành viên Nam Việt'),
                         'nam viet')

    def test_ten_khong_co_tien_to_giu_nguyen(self):
        self.assertEqual(rules.normalize('NOX ASEAN'), 'nox asean')

    def test_ten_chi_co_tien_to_thi_ra_rong(self):
        self.assertEqual(rules.normalize('Công ty TNHH'), '')


class TestDocGio(unittest.TestCase):

    def test_chua_bao_gio_nhan_sau_16h(self):
        self.assertEqual(rules.parse_hour('CHƯA BAO GIỜ nhận sau 16:00 (0/38) — xếp đầu chuyến'),
                         16.0)

    def test_gio_le(self):
        self.assertEqual(rules.parse_hour('Chưa bao giờ nhận sau 11:30'), 11.5)

    def test_cau_khong_noi_ve_gio(self):
        self.assertIsNone(rules.parse_hour('Phải đăng ký trước.'))


class TestDienGiaiLuat(unittest.TestCase):

    def setUp(self):
        self.data = {
            'thong_quan': ['Jabil'],
            'dang_ky': ['Jabil', 'Hyosung'],
            'tu_ghe': ['Kubota'],
            'cpn': ['Imarket'],
            'cuoi_chuyen': ['Ton Nam Kim'],
            'ngoai_tuyen': ['Quoc Dat'],
            'dung_rieng': {'Ton Nam Kim': 59},
            'bi_danh': {'Serveone': 'Serverone'},
            'luat': [
                {'id': 'L005', 'khach': 'Cáp điện & Hệ thống LS',
                 'luat': 'CHƯA BAO GIỜ nhận sau 16:00 (0/38) — xếp đầu chuyến chiều.'},
                {'id': 'L021', 'khach': 'Quoc Dat',
                 'luat': 'Bỏ qua nếu đơn nhỏ và sales không giục.'},
            ],
        }
        self.items = {item['key']: item for item in rules.rules_from_file(self.data)}

    def test_khach_can_ca_hai_thu_tuc_thi_la_both(self):
        # Mất một trong hai là xe đi rồi bị chặn ở cổng — lỗi đã xảy ra thật với Jabil.
        self.assertEqual(self.items['jabil']['values']['procedure_required'], 'both')

    def test_chi_mot_thu_tuc_thi_giu_nguyen(self):
        self.assertEqual(self.items['hyosung']['values']['procedure_required'], 'register')

    def test_kenh_giao(self):
        self.assertEqual(self.items['kubota']['values']['delivery_method'], 'pickup')
        self.assertEqual(self.items['imarket']['values']['delivery_method'], 'express')

    def test_diem_cuoi_chuyen_va_phut_doi_ra(self):
        values = self.items['ton nam kim']['values']
        self.assertTrue(values['must_be_last'])
        # 59 phút đo được, trừ 4 phút đã nằm sẵn trong định mức cụm.
        self.assertEqual(values['extra_service_minutes'], 55)

    def test_gio_nhan_lay_tu_cau_luat(self):
        self.assertEqual(self.items['cap dien he thong ls']['values']['receiving_to'], 16.0)

    def test_luat_khong_anh_xa_duoc_van_giu_nguyen_van(self):
        notes = self.items['quoc dat']['notes']
        self.assertTrue(any('L021' in note for note in notes))
        self.assertTrue(any('Ngoài tuyến' in note for note in notes))
        self.assertEqual(self.items['quoc dat']['values'], {})

    def test_ghi_chu_luon_kem_nguon(self):
        text = rules.note_text(['một luật'], 'khach.json 22/09')
        self.assertIn('— nguồn: khach.json 22/09', text)

    def test_khong_co_ghi_chu_thi_khong_dung_khoi_chu(self):
        self.assertEqual(rules.note_text([], 'khach.json'), '')

    def test_bi_danh_da_chuan_hoa_hai_dau(self):
        self.assertEqual(rules.alias_map(self.data), {'serveone': 'serverone'})


class TestKhopTen(unittest.TestCase):
    """Khớp theo TỪ, không theo chuỗi con — và không để tên chung kéo nhầm khách."""

    PLACES = [
        'cap dien va he thong ls viet nam',
        'nam viet packaging',
        'nam hoa',
        'hyosung dong nai',
        'hyosung viet nam',
        'coherent nt1',
    ]

    def test_thieu_mot_chu_van_khop(self):
        # File ghi "Cáp điện & Hệ thống LS", Odoo ghi thêm chữ "và" và "Việt Nam".
        self.assertEqual(rules.match_keys('cap dien he thong ls', self.PLACES),
                         ['cap dien va he thong ls viet nam'])

    def test_ten_chung_khong_keo_nham_khach(self):
        # "Nam Hoa" không được khớp "Bao bì Nam Việt" — bẫy đã được ghi lại trong file luật.
        self.assertEqual(rules.match_keys('nam hoa', self.PLACES), ['nam hoa'])

    def test_khop_dung_tuyet_doi_thi_khong_xet_them(self):
        self.assertEqual(rules.match_keys('coherent nt1', self.PLACES), ['coherent nt1'])

    def test_mot_ten_khop_nhieu_diem_thi_tra_het_cho_nguoi_chon(self):
        self.assertEqual(sorted(rules.match_keys('hyosung', self.PLACES)),
                         ['hyosung dong nai', 'hyosung viet nam'])

    def test_bi_danh_duoc_dung_khi_ten_khong_khop(self):
        places = ['jabil jtv nhon trach']
        self.assertEqual(rules.match_keys('jabil', places, {'jabil': 'jabil jtv nhon trach'}),
                         ['jabil jtv nhon trach'])

    def test_ten_toan_tu_pho_bien_thi_khong_khop_bua(self):
        self.assertEqual(rules.match_keys('viet nam', self.PLACES), [])
