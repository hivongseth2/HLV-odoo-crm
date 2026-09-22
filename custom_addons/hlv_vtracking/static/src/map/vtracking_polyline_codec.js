/* Giải mã "encoded polyline" của Google thành danh sách toạ độ để Leaflet vẽ.

   Cố tình KHÔNG viết dưới dạng module Odoo: hai bản đồ dùng nó nằm ở hai thế giới khác
   nhau — bản đồ backend là component OWL (ES module), còn trang /giao-hang là HTML tự dựng
   nạp bằng thẻ <script> thường. Đặt thành biến toàn cục là cách duy nhất để CÙNG MỘT bản
   giải mã chạy ở cả hai chỗ; viết hai bản là hai chỗ sai khác nhau về sau. Leaflet cũng
   đang được dùng theo đúng kiểu này (window.L).

   Thuật toán là của Google (Encoded Polyline Algorithm Format): mỗi giá trị là hiệu so với
   điểm trước, nhân 1e5, zigzag rồi cắt thành từng 5 bit. Không nạp thư viện ngoài cho
   chừng này việc. */

window.VtPolylineCodec = (function () {
    /**
     * @param {string} encoded chuỗi polyline từ Google
     * @returns {Array<[number, number]>} danh sách [lat, lng]; rỗng nếu chuỗi rỗng/hỏng
     */
    function decode(encoded) {
        if (!encoded || typeof encoded !== "string") {
            return [];
        }
        const points = [];
        let index = 0;
        let lat = 0;
        let lng = 0;
        while (index < encoded.length) {
            lat += readValue();
            lng += readValue();
            points.push([lat / 1e5, lng / 1e5]);
        }
        return points;

        function readValue() {
            let result = 0;
            let shift = 0;
            let byte;
            do {
                // Chuỗi hỏng giữa đường (bị cắt khi lưu, encode sai): thoát chứ không lặp
                // vô hạn. Trả về phần đọc được — vẽ thiếu một đoạn vẫn hơn treo trình duyệt.
                if (index >= encoded.length) {
                    return 0;
                }
                byte = encoded.charCodeAt(index++) - 63;
                result |= (byte & 0x1f) << shift;
                shift += 5;
            } while (byte >= 0x20);
            // Bit cuối là dấu (zigzag): số âm được mã hoá thành số lẻ.
            return result & 1 ? ~(result >> 1) : result >> 1;
        }
    }

    return { decode };
})();
