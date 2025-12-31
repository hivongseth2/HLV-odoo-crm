/** @odoo-module **/

/**
 * Patch for POS Download to handle content-disposition parsing errors.
 * 
 * The error "invalid parameter format" occurs when the content-disposition
 * library fails to parse headers with non-ASCII characters.
 * 
 * This patch intercepts the global fetch/XMLHttpRequest to sanitize
 * Content-Disposition headers before they're parsed.
 */

// Store the original getResponseHeader function
const originalXHRGetResponseHeader = XMLHttpRequest.prototype.getResponseHeader;

// Override getResponseHeader to sanitize Content-Disposition header
XMLHttpRequest.prototype.getResponseHeader = function (name) {
    const value = originalXHRGetResponseHeader.call(this, name);

    // Only sanitize Content-Disposition header
    if (name && name.toLowerCase() === 'content-disposition' && value) {
        try {
            // Check if it contains RFC2231/RFC5987 encoded filename
            if (value.includes("filename*=")) {
                // Try to convert to simple format
                // RFC5987 format: filename*=charset'language'encoded_value
                const rfc5987Match = value.match(/filename\*=([^']+)'([^']*)'([^;,]+)/);
                if (rfc5987Match) {
                    const encodedFilename = rfc5987Match[3];
                    try {
                        const decodedFilename = decodeURIComponent(encodedFilename);
                        // Create a simple ASCII-safe filename
                        const safeFilename = decodedFilename
                            .normalize("NFD").replace(/[\u0300-\u036f]/g, "") // Remove accents
                            .replace(/[^\x20-\x7E]/g, "_") // Replace other non-ASCII
                            .replace(/[,;]/g, "_") // Replace separators
                            .replace(/"/g, '\\"'); // Escape quotes
                        const disposition = value.startsWith('attachment') ? 'attachment' : 'inline';
                        const newValue = `${disposition}; filename="${safeFilename}"`;
                        console.log("POS Download: Sanitized Content-Disposition header", { original: value, sanitized: newValue });
                        return newValue;
                    } catch (decodeError) {
                        // If decode fails, use a fallback filename
                        const disposition = value.startsWith('attachment') ? 'attachment' : 'inline';
                        return `${disposition}; filename="report.pdf"`;
                    }
                }

                // Try another RFC2231 format: filename*=utf-8''encoded
                const rfc2231Match = value.match(/filename\*=([^']*'')?([^;,]+)/);
                if (rfc2231Match) {
                    const encodedFilename = rfc2231Match[2];
                    try {
                        const decodedFilename = decodeURIComponent(encodedFilename);
                        const safeFilename = decodedFilename
                            .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
                            .replace(/[^\x20-\x7E]/g, "_")
                            .replace(/[,;]/g, "_")
                            .replace(/"/g, '\\"');
                        const disposition = value.startsWith('attachment') ? 'attachment' : 'inline';
                        const newValue = `${disposition}; filename="${safeFilename}"`;
                        console.log("POS Download: Sanitized Content-Disposition header (RFC2231)", { original: value, sanitized: newValue });
                        return newValue;
                    } catch (decodeError) {
                        const disposition = value.startsWith('attachment') ? 'attachment' : 'inline';
                        return `${disposition}; filename="report.pdf"`;
                    }
                }
            }
        } catch (error) {
            console.warn("POS Download: Error sanitizing Content-Disposition header", error);
            // Return a safe fallback
            return 'attachment; filename="report.pdf"';
        }
    }

    return value;
};

console.log("POS Download: Content-Disposition header sanitization patch loaded");
