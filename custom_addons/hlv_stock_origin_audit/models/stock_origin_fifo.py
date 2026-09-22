"""Khớp FIFO giữa lượng nhập và lượng xuất của một sổ cái vị trí.

Thuần: vào list dict, ra dict. Không đụng self.env, không side effect — nhờ vậy
thuật toán này dùng lại được cho bất kỳ nguồn sự kiện nào (move line, quant
history, dữ liệu import) và test được không cần Odoo.

Vì sao FIFO: Odoo không lưu "đơn vị hàng nào đang nằm ở đâu" khi không dùng
lot/serial. Muốn trả lời "cái áo mưa này từ đâu chui ra" thì phải dựng lại:
lượng tồn hiện tại là phần *chưa bị xuất đi* của những lần nhập gần nhất, theo
giả định hàng vào trước ra trước. Giả định này sai khi kho lấy hàng lộn xộn,
nhưng nó là suy luận duy nhất nhất quán với dữ liệu move mà Odoo có.
"""

TOLERANCE = 1e-6


def attribute_fifo(events, tolerance=TOLERANCE):
    """Khớp từng lượt xuất vào các lượt nhập trước đó theo thứ tự FIFO.

    Nhận:
        events: list dict **đã sắp xếp theo thời gian tăng dần**, mỗi phần tử có
            - "key": định danh sự kiện (hashable, duy nhất trong list)
            - "qty": float có dấu. > 0 = hàng vào vị trí, < 0 = hàng rời vị trí.
            Các khoá khác bị bỏ qua, người gọi tự tra ngược bằng "key".

    Trả:
        dict gồm
        - "layers": list lớp hàng nhập theo thứ tự thời gian, mỗi lớp
          {"key", "qty_in", "qty_left", "consumed_by": [{"key", "qty"}]}.
        - "remaining": các lớp còn "qty_left" > 0 — chính là nguồn gốc của
          lượng đang tồn tại vị trí ngay lúc này.
        - "balance": tổng đại số mọi qty, tức tồn cuối theo sổ move.
        - "shortfalls": [{"key", "qty"}] phần xuất không có lớp nhập nào để
          trừ. Khác rỗng nghĩa là sổ cái không tự nhất quán (move bị xoá, tồn
          bị ghi thẳng vào DB, hoặc hàng có trước khi có move) — người gọi phải
          báo ra, không được nuốt.
        - "sources": {key_xuất: [{"key": key_nhập, "qty": float}]} lượt xuất đó
          rút từ những lớp nhập nào. Đây là thứ cho phép truy ngược sang vị trí
          nguồn: cùng một move line vừa là lượt xuất ở vị trí nguồn vừa là lượt
          nhập ở vị trí đích.

    Biên: events rỗng -> layers/remaining/shortfalls rỗng, balance 0.0.
    Sự kiện qty == 0 (trong khoảng tolerance) bị bỏ qua hoàn toàn.
    """
    layers = []
    open_idx = []  # chỉ số các lớp còn hàng, giữ đúng thứ tự FIFO
    sources = {}
    shortfalls = []
    balance = 0.0

    for event in events:
        qty = float(event.get("qty") or 0.0)
        key = event.get("key")
        balance += qty

        if qty > tolerance:
            layers.append({
                "key": key,
                "qty_in": qty,
                "qty_left": qty,
                "consumed_by": [],
            })
            open_idx.append(len(layers) - 1)
            continue

        if qty >= -tolerance:
            continue

        need = -qty
        drawn = []
        while need > tolerance and open_idx:
            layer = layers[open_idx[0]]
            take = min(layer["qty_left"], need)
            layer["qty_left"] -= take
            layer["consumed_by"].append({"key": key, "qty": take})
            drawn.append({"key": layer["key"], "qty": take})
            need -= take
            if layer["qty_left"] <= tolerance:
                layer["qty_left"] = 0.0
                open_idx.pop(0)
        sources[key] = drawn
        if need > tolerance:
            shortfalls.append({"key": key, "qty": need})

    return {
        "layers": layers,
        "remaining": [lay for lay in layers if lay["qty_left"] > tolerance],
        "balance": balance,
        "shortfalls": shortfalls,
        "sources": sources,
    }


def split_proportionally(parts, amount, tolerance=TOLERANCE):
    """Chia `amount` cho các phần tử `parts` theo đúng tỷ lệ qty của chúng.

    parts: list dict có khoá "qty". Trả list float cùng độ dài, tổng bằng
    `amount` (sai số làm tròn dồn vào phần tử cuối).

    Dùng khi một lượt nhập được truy ngược ra nhiều nguồn nhưng chỉ còn *một
    phần* lượng nhập đó đang tồn: phần còn lại phải chia đều theo tỷ lệ chứ
    không gán hết cho nguồn đầu tiên.

    Biên: parts rỗng -> []; tổng qty của parts bằng 0 -> chia đều.
    """
    if not parts:
        return []
    total = sum(float(p.get("qty") or 0.0) for p in parts)
    if total <= tolerance:
        even = amount / len(parts)
        return [even] * len(parts)
    out = [amount * (float(p.get("qty") or 0.0) / total) for p in parts]
    out[-1] += amount - sum(out)
    return out
