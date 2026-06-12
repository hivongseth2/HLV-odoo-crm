/** @odoo-module **/

let googleMapsPromise = null;

export function loadGoogleMaps(apiKey, libraries = ["places", "geometry", "routes"]) {
    if (window.google && window.google.maps) {
        return Promise.resolve(window.google.maps);
    }
    if (!apiKey) {
        return Promise.reject(new Error("Missing Google Maps API key"));
    }
    if (googleMapsPromise) {
        return googleMapsPromise;
    }

    googleMapsPromise = new Promise((resolve, reject) => {
        const callbackName = `hlvGoogleMapsReady_${Date.now()}`;
        window[callbackName] = () => {
            delete window[callbackName];
            resolve(window.google.maps);
        };

        const script = document.createElement("script");
        script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}&libraries=${libraries.join(",")}&callback=${callbackName}`;
        script.async = true;
        script.defer = true;
        script.onerror = () => {
            delete window[callbackName];
            googleMapsPromise = null;
            reject(new Error("Cannot load Google Maps"));
        };
        document.head.appendChild(script);
    });

    return googleMapsPromise;
}

export function getCurrentPosition(options = {}) {
    if (!navigator.geolocation) {
        return Promise.reject(new Error("Geolocation is not supported"));
    }
    return new Promise((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, {
            enableHighAccuracy: true,
            timeout: 12000,
            maximumAge: 60000,
            ...options,
        });
    });
}

// Keep geocoding behind one util so later caching can be added here without touching UI flows.
export async function searchPlaceGeocode(address, options = {}) {
    const maps = await loadGoogleMaps(options.apiKey);
    const geocoder = options.geocoder || new maps.Geocoder();
    const request = {
        address,
        componentRestrictions: options.country ? { country: options.country } : undefined,
    };

    return new Promise((resolve, reject) => {
        geocoder.geocode(request, (results, status) => {
            if (status !== "OK" || !results || !results.length) {
                reject(new Error(`Geocode failed: ${status}`));
                return;
            }
            const place = results[0];
            const location = place.geometry.location;
            resolve({
                formattedAddress: place.formatted_address,
                placeId: place.place_id,
                lat: location.lat(),
                lng: location.lng(),
                raw: place,
            });
        });
    });
}

export async function geocodeStops(stops, options = {}) {
    const maps = await loadGoogleMaps(options.apiKey);
    const geocoder = new maps.Geocoder();
    const results = [];
    const errors = [];

    for (const stop of stops) {
        try {
            const geocode = await searchPlaceGeocode(stop.address, {
                ...options,
                geocoder,
            });
            results.push({ ...stop, geocode });
        } catch (error) {
            errors.push({ stop, error: error.message });
        }
    }

    return { stops: results, errors };
}
