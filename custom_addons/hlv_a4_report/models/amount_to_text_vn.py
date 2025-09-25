# hlv_a4_report/models/amount_to_text_vn.py
from odoo import models, api

class HlvAmount(models.AbstractModel):
    _name = 'hlv.amount'
    _description = 'Amount to Vietnamese words'

    _UNITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]

    def _read_three(self, n, full):
        """Đọc 3 chữ số: n = 0..999, full = có đọc đủ trăm/chục không"""
        tram = n // 100
        chuc = (n % 100) // 10
        donvi = n % 10
        parts = []
        if full or tram > 0:
            parts.append(self._UNITS[tram] + " trăm")
            if chuc == 0 and donvi != 0:
                parts.append("lẻ")
        if chuc > 1:
            parts.append(self._UNITS[chuc] + " mươi")
            if donvi == 1:
                parts.append("mốt")
            elif donvi == 5:
                parts.append("lăm")
            elif donvi != 0:
                parts.append(self._UNITS[donvi])
        elif chuc == 1:
            parts.append("mười")
            if donvi == 5:
                parts.append("lăm")
            elif donvi != 0:
                parts.append(self._UNITS[donvi])
        else:
            if donvi != 0 and (full or tram > 0):
                parts.append(self._UNITS[donvi])
            elif donvi != 0:
                parts.append(self._UNITS[donvi])
        return " ".join(parts).strip()

    @api.model
    def amount_to_text_vn(self, amount):
        """Chuyển số nguyên VND -> chữ (không đọc phần lẻ).
           Ví dụ: 1523000 -> 'một triệu năm trăm hai mươi ba nghìn đồng'"""
        try:
            n = int(round(amount or 0))
        except Exception:
            n = 0
        if n == 0:
            return "không đồng"
        suffixes = ["", " nghìn", " triệu", " tỷ", " nghìn tỷ", " triệu tỷ"]
        parts = []
        i = 0
        full = False
        while n > 0 and i < len(suffixes):
            block = n % 1000
            if block > 0:
                seg = self._read_three(block, full)
                if seg:
                    parts.append(seg + suffixes[i])
                full = True
            n //= 1000
            i += 1
        s = " ".join(reversed(parts)).strip()
        # Chuẩn hóa một vài chỗ
        s = s.replace("mươi một", "mươi mốt")
        s = s.replace("mươi năm", "mươi lăm")
        s = s.replace("mười năm", "mười lăm")
        return s + " đồng"
