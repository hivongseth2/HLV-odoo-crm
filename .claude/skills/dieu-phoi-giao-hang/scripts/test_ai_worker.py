"""Test phần thuần của worker. Chạy::

    py -m unittest discover -s .claude/skills/dieu-phoi-giao-hang/scripts -p "test_*.py"

Đọc sai khung websocket là worker bỏ sót yêu cầu mà không ai biết — nên phần đọc khung có
test cho cả tin lạ lẫn khung hỏng.
"""

import unittest

import ai_worker


def frame(*items):
    import json
    return json.dumps(list(items))


def notification(notification_id, message_type, payload):
    return {'id': notification_id, 'message': {'type': message_type, 'payload': payload}}


class TestDocKhungBus(unittest.TestCase):

    def test_lay_dung_id_yeu_cau(self):
        raw = frame(notification(7, 'hlv_vtracking/ai_request', {'request_id': 12}),
                    notification(8, 'hlv_vtracking/ai_request', {'request_id': 13}))
        self.assertEqual(ai_worker.request_ids_from_frame(raw), ([12, 13], 8))

    def test_bo_qua_tin_loai_khac(self):
        raw = frame(notification(9, 'mail.message/inbox', {'request_id': 99}),
                    notification(10, 'hlv_vtracking/ai_request', {'request_id': 5}))
        self.assertEqual(ai_worker.request_ids_from_frame(raw), ([5], 10))

    def test_khung_hong_khong_lam_chet_worker(self):
        self.assertEqual(ai_worker.request_ids_from_frame('{khong phai json'), ([], 0))
        self.assertEqual(ai_worker.request_ids_from_frame('{"event": "pong"}'), ([], 0))

    def test_tin_thieu_payload(self):
        raw = frame(notification(3, 'hlv_vtracking/ai_request', {}))
        self.assertEqual(ai_worker.request_ids_from_frame(raw), ([], 3))


class TestLenhChayClaude(unittest.TestCase):

    def test_chi_cho_phep_goi_vt(self):
        command = ai_worker.claude_command('claude.exe', 'làm việc đi')
        self.assertEqual(command[:2], ['claude.exe', '-p'])
        self.assertIn('--allowed-tools', command)
        self.assertNotIn('Write', command)
        self.assertNotIn('Edit', command)
        self.assertTrue(any(item.startswith('Bash(py ') for item in command))

    def test_loi_nhac_neu_ro_id_va_bat_buoc_tra_loi(self):
        prompt = ai_worker.prompt_for({'id': 42, 'request_type_label': 'Xin giao sớm hơn',
                                       'requester': 'Trâm'})
        self.assertIn('#42', prompt)
        self.assertIn('requests/42/answer', prompt)
        self.assertIn('requests/42/fail', prompt)


class TestDiaChiWebsocket(unittest.TestCase):

    def test_https_thanh_wss(self):
        self.assertEqual(ai_worker.websocket_url('https://a.odoo.com'),
                         'wss://a.odoo.com/websocket')

    def test_http_thanh_ws(self):
        self.assertEqual(ai_worker.websocket_url('http://localhost:8069'),
                         'ws://localhost:8069/websocket')


if __name__ == '__main__':
    unittest.main()
