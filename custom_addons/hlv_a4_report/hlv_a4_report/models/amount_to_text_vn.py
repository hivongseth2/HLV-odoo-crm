from odoo import models, api

class HlvAmount(models.AbstractModel):
    _name = 'hlv.amount'
    _description = 'Amount to Vietnamese words'

    _UNITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]

    def _read_three(self, n, is_first_block=False):
        """Đọc 3 chữ số: n = 0..999
        is_first_block: True nếu đây là khối đầu tiên (có giá trị lớn nhất)
        """
        if n == 0:
            return ""
            
        tram = n // 100
        chuc = (n % 100) // 10
        donvi = n % 10
        parts = []
        
        # Xử lý hàng trăm
        if tram > 0:
            parts.append(self._UNITS[tram] + " trăm")
            # Chỉ thêm "lẻ" khi có hàng trăm và hàng chục = 0 nhưng có đơn vị
            if chuc == 0 and donvi != 0:
                parts.append("lẻ")
        
        # Xử lý hàng chục và đơn vị
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
        else:  # chuc == 0
            if donvi != 0:
                # Với khối đầu tiên, chỉ đọc số đơn vị (ví dụ: "một" thay vì "không trăm lẻ một")
                # Với khối khác, cần kiểm tra xem có cần "lẻ" không
                if tram == 0 and is_first_block:
                    parts.append(self._UNITS[donvi])
                elif tram > 0:  # Đã có "lẻ" ở trên
                    parts.append(self._UNITS[donvi])
                else:  # tram == 0 và không phải khối đầu
                    parts.append(self._UNITS[donvi])
        
        return " ".join(parts).strip()

    @api.model
    def amount_to_text_vn(self, amount):
        """Chuyển số nguyên VND -> chữ (không đọc phần lẻ).
           Ví dụ: 1204800 -> 'một triệu hai trăm lẻ bốn nghìn tám trăm đồng'"""
        try:
            n = int(round(amount or 0))
        except Exception:
            n = 0
            
        if n == 0:
            return "không đồng"
        
        if n < 0:
            return "âm " + self.amount_to_text_vn(-n)
        
        suffixes = ["", " nghìn", " triệu", " tỷ", " nghìn tỷ", " triệu tỷ"]
        blocks = []
        
        # Tách thành các khối 3 chữ số
        temp_n = n
        while temp_n > 0:
            blocks.append(temp_n % 1000)
            temp_n //= 1000
        
        parts = []
        for i, block in enumerate(reversed(blocks)):
            if block > 0:
                is_first = (i == 0)  # Khối đầu tiên (có giá trị lớn nhất)
                seg = self._read_three(block, is_first)
                if seg:
                    suffix_index = len(blocks) - 1 - i
                    if suffix_index < len(suffixes):
                        parts.append(seg + suffixes[suffix_index])
        
        if not parts:
            return "không đồng"
        
        result = " ".join(parts).strip()
        
        # Chuẩn hóa một số trường hợp đặc biệt
        result = result.replace("mười một", "mười mốt")
        result = result.replace("mười năm", "mười lăm") 
        result = result.replace("mươi một", "mươi mốt")
        result = result.replace("mươi năm", "mươi lăm")
        
        return result + " đồng"

# Test cases để kiểm tra
if __name__ == "__main__":
    hlv = HlvAmount()
    test_cases = [
        1204800,  # một triệu hai trăm lẻ bốn nghìn tám trăm đồng
        1000000,  # một triệu đồng
        204800,   # hai trăm lẻ bốn nghìn tám trăm đồng
        4800,     # bốn nghìn tám trăm đồng
        800,      # tám trăm đồng
        15,       # mười lăm đồng
        1,        # một đồng
        0,        # không đồng
        101,      # một trăm lẻ một đồng
        1001,     # một nghìn lẻ một đồng
    ]
    
    for amount in test_cases:
        print(f"{amount:,} -> {hlv.amount_to_text_vn(amount)}")