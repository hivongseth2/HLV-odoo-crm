/**
 * Service Worker for HLV Barcode Shipper
 * Provides basic offline support and caching
 */

const CACHE_NAME = 'hlv-barcode-shipper-v1';
const urlsToCache = [
    '/hlv_barcode_shipper/static/src/css/barcode_shipper.css',
    '/hlv_barcode_shipper/static/src/js/barcode_scanner.js',
    '/barcode/shipper'
];

// Install event - cache resources
self.addEventListener('install', function(event) {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(function(cache) {
                return cache.addAll(urlsToCache);
            })
    );
});

// Fetch event - serve from cache when offline
self.addEventListener('fetch', function(event) {
    event.respondWith(
        caches.match(event.request)
            .then(function(response) {
                // Return cached version or fetch from network
                return response || fetch(event.request);
            }
        )
    );
});

// Activate event - clean up old caches
self.addEventListener('activate', function(event) {
    event.waitUntil(
        caches.keys().then(function(cacheNames) {
            return Promise.all(
                cacheNames.map(function(cacheName) {
                    if (cacheName !== CACHE_NAME) {
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );
});