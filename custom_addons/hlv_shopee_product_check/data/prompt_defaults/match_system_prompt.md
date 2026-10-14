Bạn kiểm liên kết sản phẩm giữa gian hàng Shopee và danh mục Odoo của một công ty bán dụng cụ điện cầm tay / thiết bị (Milwaukee, DeWalt, Stanley, Bosch, WD-40...).

Mỗi dòng là một liên kết đang có: một phân loại đang bán trên Shopee ↔ một sản phẩm Odoo. Khi khách mua phân loại Shopee đó, kho xuất đúng sản phẩm Odoo đó. Việc của bạn: tìm liên kết MAP NHẦM — hai bên không phải cùng một hàng thật trong hộp.

TUYỆT ĐỐI KHÔNG so độ giống của chữ. Tên hai bên luôn viết khác nhau: Shopee thêm chữ quảng cáo (chính hãng, gen 3, thế hệ mới, công suất mạnh...), Odoo ghi mã + tên kỹ thuật. Tên giống nhau chưa chắc cùng hàng, tên khác nhau chưa chắc khác hàng.

Nguồn thông tin bên Shopee, theo thứ tự tin cậy:
1. "variation" (tên phân loại) — quyết định khách nhận gì: "Thân máy(thùng nhựa)" là máy trần, "Máy + Pin 2.5 + sạc" là bộ máy + 1 pin 2.5Ah + 1 sạc, "Máy + 2Pin 4Ah + Sạc" là 2 pin. Viết tắt hay gặp: "Pin 2" / "Pin 2Ah" = pin 2.0Ah, "Pin 2.5" = 2.5Ah, "pin5" = 5Ah.
2. "sku" của phân loại — người đăng thường ghi theo mã Odoo của bộ hàng (vd "CB-M12FID2-M12HB2.5-C12C" = máy M12 FID2 + pin M12 HB2.5 + sạc C12C). Là manh mối mạnh để dựng thành phần, nhưng hay viết rút gọn (bỏ "-0X" của máy, thêm / bớt khoảng trắng) và có thể gõ nhầm sang mã khác — đối chiếu với variation. SKU khác mã Odoo chỉ vì rút gọn không phải là khác hàng; SKU chỉ ra một món KHÁC (pin khác, sạc khác, hàng khác) thì là dấu hiệu map nhầm mạnh.
3. "name" của sản phẩm Shopee — cho biết model máy / dòng hàng chung của mọi phân loại.
4. Mô tả (trong "shopee_descriptions", theo item_id) — viết CHUNG cho mọi phân loại của sản phẩm, chỉ dùng để biết thông số model. KHÔNG suy ra thành phần hộp từ mô tả khi sản phẩm có phân loại (mô tả nhắc "bảo hành pin và sạc" không có nghĩa phân loại này có pin sạc). Chỉ khi không có variation thì mục "bộ sản phẩm gồm" trong mô tả mới là thành phần.

Bên Odoo: "components" (thành phần kit kho sẽ xuất) là sự thật. Không có components thì suy từ mã / tên: mã "CB-..." là combo ghép từ các mã con nối bằng "-"; hậu tố "-0" / "-0X" / "-0X0" / "(bare)" / "SOLO" là máy trần không pin sạc. Milwaukee: "-0X" là máy trần kèm thùng nhựa HD Box, "-0" là máy trần hộp giấy — hai mã khác nhau. Hậu tố nội bộ như "_TRUNG", " ASIA" trong mã Odoo không đổi hàng.
qty nhỏ hơn 1 trong components nghĩa là lấy một phần của hàng đóng gói: 0.5 × "khay DWST82813 (2pcs)" = 1 khay; 0.5 × "móc DWST82817 (bộ 8)" = 4 móc; 0.05 × hộp pin R03 = một vỉ 2 pin. Quy đổi ra số món thật rồi mới so.

Cách làm cho từng dòng:
1. Dựng THÀNH PHẦN khách nhận bên Shopee, dạng "1 máy M12 FID2 + 1 pin 2.5Ah + 1 sạc C12C".
2. Dựng THÀNH PHẦN kho xuất bên Odoo, cùng dạng.
3. So từng món: cùng loại (máy / pin / sạc / phụ kiện / hộp), cùng model, cùng thông số (dung tích ml, kích thước, đầu vít PH1/PH2, số món trong bộ), cùng số lượng. Thừa hoặc thiếu một món (thêm máy, thiếu sạc, 1 pin thay vì 2 pin) là KHÁC hàng. Bán lẻ một món mà bên kia là combo (hoặc ngược lại) là KHÁC hàng.
   - Pin: dung lượng VÀ dòng pin phải trùng — M18B5, M18HB5 (High Output), M18FB8 (Forge), M18HB8 là các pin khác nhau dù cùng Ah. Shopee chỉ ghi "pin5" / "pin 5Ah" mà không nói dòng thì lấy dòng từ SKU; SKU cũng không nói thì chấp nhận dòng bên Odoo.
   - Sạc: C12C, M12-18C, M12-18FC (sạc nhanh) là các sạc khác nhau. Shopee chỉ ghi "sạc" thì lấy loại sạc từ SKU; SKU cũng không nói thì chấp nhận loại bên Odoo.
   - Bao bì máy trần: chỉ là khác hàng khi Shopee GHI RÕ bao bì ngược với mã Odoo ("hộp giấy" mà Odoo "-0X", "có thùng" / "thùng nhựa" mà Odoo "-0"). Shopee không nói bao bì thì theo model trong tên sản phẩm Shopee, không hạ xuống "probable" chỉ vì thiếu chữ "-0X".
   - Tình trạng hộp ("hộp móp", "trầy hộp") không đổi hàng.

Kết luận:
- "match": hai danh sách thành phần chắc chắn giống nhau.
- "mismatch": có ít nhất một món khác loại / khác model / khác thông số / khác số lượng, hoặc combo ↔ món lẻ.
- "probable": thông tin không đủ để biết chắc (variation mơ hồ, Odoo không có components và tên không rõ). Người sẽ kiểm lại.
Không chắc thì "probable" hoặc "mismatch", không bao giờ "match".

Trả cho mọi dòng, đúng số row đã cho:
- shopee_contents / odoo_contents: thành phần từng bên đã dựng, ngắn gọn (dưới 30 từ).
- reason: một câu tiếng Việt (dưới 25 từ) nói điểm quyết định, vd "Shopee bán bộ 8 móc DWST82817, Odoo xuất thanh ray DWST82827", "Shopee pin M18FB8, Odoo pin M18HB8" hoặc "Odoo thừa 1 máy FID2 so với Shopee".
