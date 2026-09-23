/**
 * camera_health.js — phán đoán luồng camera còn sống hay đã chết, thuần từ pixel.
 *
 * Ba kiểu hỏng của cầu nối OBS → Virtual Camera đều quy về một dấu hiệu:
 *   - nguồn VLC lỗi        -> khung hình đen
 *   - OBS hiện màn hình chờ -> ảnh tĩnh
 *   - camera IP treo        -> đứng hình
 *
 * Mấu chốt: camera thật KHÔNG BAO GIỜ cho ra hai khung hình giống hệt nhau —
 * nhiễu cảm biến luôn làm xê dịch các bit thấp, kể cả khi không ai đứng trước
 * bàn. Còn ảnh do OBS bơm ra là ảnh tĩnh, giống nhau từng pixel. Nhờ vậy mới
 * phân biệt được mà không cần ngưỡng chỉnh riêng theo từng kho.
 *
 * File này thuần: không đụng DOM, không mạng, không biến toàn cục. Bên gọi tự
 * lấy pixel rồi truyền vào.
 */
var CameraHealth = (() => {

  // Dưới các ngưỡng này thì coi là hỏng. Để rộng rãi có chủ ý: chỉ bắt những ca
  // hỏng không thể chối cãi, tránh chặn oan dây chuyền đóng gói.
  const BLACK_MAX_LUMA = 10;        // gần như đen kịt
  const BLACK_MAX_SPREAD = 4;       // ... và phẳng lì, không có chi tiết gì
  const STATIC_MAX_DIFF = 2;        // lệch luma tối đa trên một pixel vẫn coi là "y hệt"
  const STATIC_MAX_CHANGED_RATIO = 0.02;  // dưới 2% pixel đổi -> coi như ảnh tĩnh

  /**
   * Tính chữ ký độ sáng của một khung hình.
   * @param {{data: Uint8ClampedArray, width: number, height: number}} imageData
   *        Pixel RGBA, thường lấy từ ctx.getImageData() của một canvas dò cỡ nhỏ.
   * @returns {Uint8Array} Một giá trị luma 0..255 cho mỗi pixel, đúng thứ tự gốc.
   *          Trả mảng rỗng nếu imageData không hợp lệ.
   */
  function frameSignature(imageData) {
    const d = imageData && imageData.data;
    if (!d || !d.length) return new Uint8Array(0);
    const n = d.length >> 2;
    const sig = new Uint8Array(n);
    for (let i = 0; i < n; i++) {
      const p = i << 2;
      sig[i] = (d[p] * 299 + d[p + 1] * 587 + d[p + 2] * 114) / 1000;
    }
    return sig;
  }

  /**
   * Độ sáng trung bình của một chữ ký.
   * @param {Uint8Array} sig
   * @returns {number} 0..255; trả 0 nếu chữ ký rỗng.
   */
  function meanLuma(sig) {
    if (!sig || !sig.length) return 0;
    let sum = 0;
    for (let i = 0; i < sig.length; i++) sum += sig[i];
    return sum / sig.length;
  }

  /**
   * Độ lệch chuẩn độ sáng trong một khung hình — đo xem ảnh có chi tiết không.
   * @param {Uint8Array} sig
   * @returns {number} 0 nghĩa là ảnh phẳng tuyệt đối; trả 0 nếu chữ ký rỗng.
   */
  function lumaSpread(sig) {
    if (!sig || !sig.length) return 0;
    const m = meanLuma(sig);
    let acc = 0;
    for (let i = 0; i < sig.length; i++) {
      const d = sig[i] - m;
      acc += d * d;
    }
    return Math.sqrt(acc / sig.length);
  }

  /**
   * So hai chữ ký khung hình lấy ở hai thời điểm.
   * @param {Uint8Array} a chữ ký trước
   * @param {Uint8Array} b chữ ký sau
   * @returns {{maxDiff: number, changedRatio: number}} maxDiff là chênh lệch luma
   *          lớn nhất trên một pixel, changedRatio là tỉ lệ pixel lệch quá
   *          STATIC_MAX_DIFF.
   *          Biên: hai chữ ký rỗng hoặc lệch độ dài -> {maxDiff: 0, changedRatio: 0},
   *          tức là coi như KHÔNG đổi. Cố ý nghiêng về phía báo hỏng: thà cảnh
   *          báo nhầm còn hơn để lọt một phiếu đóng gói không có hình.
   */
  function frameDelta(a, b) {
    if (!a || !b || !a.length || a.length !== b.length) {
      return { maxDiff: 0, changedRatio: 0 };
    }
    let maxDiff = 0, changed = 0;
    for (let i = 0; i < a.length; i++) {
      const d = Math.abs(a[i] - b[i]);
      if (d > maxDiff) maxDiff = d;
      if (d > STATIC_MAX_DIFF) changed++;
    }
    return { maxDiff, changedRatio: changed / a.length };
  }

  /**
   * Kết luận luồng camera còn sống không, từ một dãy chữ ký lấy cách nhau vài giây.
   * @param {Uint8Array[]} signatures theo thứ tự thời gian, cần ít nhất 2 mẫu.
   * @returns {{alive: boolean, reason: string, detail: object}}
   *          reason: 'ok' | 'black' | 'static' | 'unknown'.
   *          Biên: dưới 2 mẫu -> reason 'unknown' và alive = true, để lúc mới mở
   *          camera chưa kịp lấy đủ mẫu thì không chặn oan.
   */
  function assessFeed(signatures) {
    const sigs = (signatures || []).filter(s => s && s.length);
    if (sigs.length < 2) {
      return { alive: true, reason: 'unknown', detail: { samples: sigs.length } };
    }

    const last = sigs[sigs.length - 1];
    const mean = meanLuma(last);
    const spread = lumaSpread(last);
    if (mean <= BLACK_MAX_LUMA && spread <= BLACK_MAX_SPREAD) {
      return { alive: false, reason: 'black', detail: { mean, spread } };
    }

    // Chỉ cần MỘT cặp khung hình có thay đổi thật là đủ kết luận còn sống.
    let maxChangedRatio = 0, maxPixelDiff = 0;
    for (let i = 1; i < sigs.length; i++) {
      const d = frameDelta(sigs[i - 1], sigs[i]);
      if (d.changedRatio > maxChangedRatio) maxChangedRatio = d.changedRatio;
      if (d.maxDiff > maxPixelDiff) maxPixelDiff = d.maxDiff;
      if (d.changedRatio >= STATIC_MAX_CHANGED_RATIO) {
        return { alive: true, reason: 'ok', detail: { changedRatio: d.changedRatio } };
      }
    }
    return {
      alive: false,
      reason: 'static',
      detail: { changedRatio: maxChangedRatio, maxPixelDiff, samples: sigs.length },
    };
  }

  /**
   * Câu chữ tiếng Việt cho người đóng gói đọc, ứng với reason của assessFeed().
   * @param {string} reason
   * @returns {string} Biên: reason lạ -> câu chung chung, không bao giờ trả rỗng.
   */
  function describe(reason) {
    if (reason === 'black') {
      return 'Camera đen hình — nguồn VLC trong OBS đã chết.';
    }
    if (reason === 'static') {
      return 'Camera đứng hình — OBS đang ở màn hình chờ hoặc nguồn VLC chưa chạy.';
    }
    if (reason === 'nocam') {
      return 'Không mở được camera — OBS chưa bật Virtual Camera, hoặc thiết bị đang bị ứng dụng khác chiếm.';
    }
    if (reason === 'hidden') {
      return 'Màn hình đóng gói bị chuyển sang tab khác lúc đang quay — đoạn đó video gần như đứng hình.';
    }
    return 'Camera không có tín hiệu hợp lệ.';
  }

  return {
    BLACK_MAX_LUMA, BLACK_MAX_SPREAD, STATIC_MAX_DIFF, STATIC_MAX_CHANGED_RATIO,
    frameSignature, meanLuma, lumaSpread, frameDelta, assessFeed, describe,
  };
})();
