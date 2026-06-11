/** @odoo-module **/

export function toLatLng(point) {
    if (!point) {
        return null;
    }
    if (typeof point.lat === "function") {
        return { lat: point.lat(), lng: point.lng() };
    }
    return { lat: Number(point.lat), lng: Number(point.lng) };
}

export function distanceMeters(a, b) {
    const p1 = toLatLng(a);
    const p2 = toLatLng(b);
    if (!p1 || !p2) {
        return 0;
    }
    const radius = 6371000;
    const dLat = (p2.lat - p1.lat) * Math.PI / 180;
    const dLng = (p2.lng - p1.lng) * Math.PI / 180;
    const lat1 = p1.lat * Math.PI / 180;
    const lat2 = p2.lat * Math.PI / 180;
    const h =
        Math.sin(dLat / 2) * Math.sin(dLat / 2) +
        Math.cos(lat1) * Math.cos(lat2) *
        Math.sin(dLng / 2) * Math.sin(dLng / 2);
    return 2 * radius * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}

export function sortNearestStops(origin, stops) {
    const pending = [...stops];
    const ordered = [];
    let cursor = origin;

    while (pending.length) {
        let nearestIndex = 0;
        let nearestDistance = Number.POSITIVE_INFINITY;
        pending.forEach((stop, index) => {
            const distance = distanceMeters(cursor, stop.geocode);
            if (distance < nearestDistance) {
                nearestDistance = distance;
                nearestIndex = index;
            }
        });
        const [next] = pending.splice(nearestIndex, 1);
        ordered.push(next);
        cursor = next.geocode;
    }

    return ordered;
}

export function formatDistance(meters) {
    if (!meters) {
        return "0 km";
    }
    if (meters < 1000) {
        return `${Math.round(meters)} m`;
    }
    return `${(meters / 1000).toFixed(1)} km`;
}

export function formatDuration(seconds) {
    if (!seconds) {
        return "0 phút";
    }
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) {
        return `${minutes} phút`;
    }
    const hours = Math.floor(minutes / 60);
    const remain = minutes % 60;
    return remain ? `${hours}h ${remain}m` : `${hours}h`;
}
