/** @odoo-module **/

/* Nạp Leaflet từ CDN đúng MỘT lần cho cả phiên làm việc.

   Tách khỏi component vì hai lý do: component có thể bị dựng lại nhiều lần khi người dùng
   đi ra đi vào màn hình, và việc "đã nạp hay chưa" là trạng thái của trang chứ không phải
   của component. */

const LEAFLET_VERSION = "1.9.4";
const SCRIPT_URL = `https://unpkg.com/leaflet@${LEAFLET_VERSION}/dist/leaflet.js`;
const STYLE_URL = `https://unpkg.com/leaflet@${LEAFLET_VERSION}/dist/leaflet.css`;

// Ghim đúng một phiên bản: bản đồ vỡ sau một đêm vì CDN đẩy bản mới là lỗi rất khó tìm.
let loadingPromise = null;

export function loadLeaflet() {
    if (window.L) {
        return Promise.resolve(window.L);
    }
    if (loadingPromise) {
        return loadingPromise;
    }
    loadingPromise = new Promise((resolve, reject) => {
        if (!document.querySelector(`link[href="${STYLE_URL}"]`)) {
            const link = document.createElement("link");
            link.rel = "stylesheet";
            link.href = STYLE_URL;
            document.head.appendChild(link);
        }
        const script = document.createElement("script");
        script.src = SCRIPT_URL;
        script.async = true;
        script.onload = () => {
            if (window.L) {
                resolve(window.L);
            } else {
                reject(new Error("Tải được thư viện bản đồ nhưng không khởi tạo được."));
            }
        };
        script.onerror = () => {
            // Lỗi này gần như luôn là mạng nội bộ chặn CDN. Nói thẳng cách xử lý, vì
            // người đọc thông báo là quản lý đội xe chứ không phải quản trị mạng.
            loadingPromise = null;
            reject(
                new Error(
                    "Không tải được thư viện bản đồ từ unpkg.com. Máy chủ hoặc mạng công ty " +
                        "có thể đang chặn. Danh sách xe bên dưới vẫn dùng bình thường."
                )
            );
        };
        document.head.appendChild(script);
    });
    return loadingPromise;
}
