// hlv_barcode_shipper/static/src/js/sw.js
// Đổi tên cache để máy đang giữ bản v1 xóa cache cũ khi SW mới kích hoạt.
const CACHE_NAME = 'hlv-barcode-shipper-v2';
const urlsToCache = [
    '/hlv_barcode_shipper/static/src/css/barcode_shipper.css',
    '/hlv_barcode_shipper/static/src/js/barcode_scanner.js',
    '/barcode/shipper',
];

self.addEventListener('install', event => {
    // Không chờ shipper đóng hết tab mới kích hoạt — app mở cả ngày nên sẽ không bao giờ đóng.
    self.skipWaiting();
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(urlsToCache))
    );
});

// Mạng trước, cache chỉ để dùng khi rớt mạng. Bản v1 lấy cache trước nên điện thoại chạy mãi
// JS cũ, sửa code trên server không tới được tay shipper.
self.addEventListener('fetch', event => {
    const req = event.request;
    if (req.method !== 'GET' || !urlsToCache.includes(new URL(req.url).pathname)) return;
    event.respondWith(
        fetch(req)
            .then(res => {
                if (res.ok) {
                    const copy = res.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(req, copy));
                }
                return res;
            })
            .catch(() => caches.match(req))
    );
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys()
            .then(names =>
                Promise.all(
                    names.map(name => {
                        if (name !== CACHE_NAME) return caches.delete(name);
                    })
                )
            )
            .then(() => self.clients.claim())
    );
});
