// hlv_barcode_shipper/static/src/js/sw.js
const CACHE_NAME = 'hlv-barcode-shipper-v1';
const urlsToCache = [
    '/hlv_barcode_shipper/static/src/css/barcode_shipper.css',
    '/hlv_barcode_shipper/static/src/js/barcode_scanner.js',
    '/barcode/shipper',
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(urlsToCache))
    );
});

self.addEventListener('fetch', event => {
    event.respondWith(
        caches.match(event.request).then(r => r || fetch(event.request))
    );
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(names =>
            Promise.all(
                names.map(name => {
                    if (name !== CACHE_NAME) return caches.delete(name);
                })
            )
        )
    );
});
