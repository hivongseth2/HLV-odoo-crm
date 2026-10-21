/**
 * pack_video_extra.js — màn hình quay video bổ sung cho phiếu PACK đã xong.
 * Không quét hàng: mở trang là quay, bấm Xong là dừng, gửi hết rồi về màn quét.
 *
 * Depends on:
 *   toast.js          — toast notifications
 *   recording.js      — startRecording, stopRecording, diag, isRecording
 */
document.addEventListener('DOMContentLoaded', () => {
  const doneBtn = document.getElementById('extra_video_done_btn');
  if (!doneBtn) return;

  const backToScan = () => { window.location.href = '/custom_barcode_scan/ui'; };

  doneBtn.addEventListener('click', async () => {
    if (!isRecording) {
      toast.warn('Chưa quay được gì nên không có video để gửi.', { ms: 2500 });
      setTimeout(backToScan, 1500);
      return;
    }
    doneBtn.disabled = true;
    doneBtn.textContent = 'Đang gửi video...';
    // Chờ gửi hết, không cắt ở 5 giây như nút Hoàn tất của màn hình đóng gói:
    // ở đây video chính là toàn bộ việc cần làm, rời trang sớm là mất đoạn cuối
    // còn nằm trong trình duyệt.
    await stopRecording();
    toast.success('Đã gửi video bổ sung.', { ms: 1200 });
    setTimeout(backToScan, 600);
  });

  diag();
  setTimeout(startRecording, 400);
});
