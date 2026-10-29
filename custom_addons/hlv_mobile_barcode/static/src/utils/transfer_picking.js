/** @odoo-module **/

// Số phiếu chuyển nội bộ: INT (chuyển trong kho, phiếu cũ), CKD (chuyển kho đi — bước 1), CKN (nhận chuyển kho — bước 2).
const TRANSFER_PICKING_NAME = /INT|\/CK[DN]\//;

/**
 * Phiếu có phải phiếu chuyển nội bộ / chuyển kho không, nhận diện theo số phiếu.
 * @param {string} pickingName số phiếu, vd "TSN/CKD/00012"
 * @returns {boolean} true nếu là phiếu INT/CKD/CKN; false khi rỗng hoặc loại khác (PICK, IN, OUT...)
 */
export function isTransferPickingName(pickingName) {
    return Boolean(pickingName) && TRANSFER_PICKING_NAME.test(pickingName);
}
