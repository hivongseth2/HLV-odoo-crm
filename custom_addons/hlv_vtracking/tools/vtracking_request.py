"""Luật trạng thái của phiếu yêu cầu gửi AI — hàm thuần, vào gì ra nấy.

Vòng đời một phiếu::

    pending ──claim──> processing ──answer──> answered ──duyệt──> pending (approved)
                          │                      │                      │
                          └──fail──> failed      └──từ chối──> rejected └──answer(applied)──> done

Hai điều quan trọng nằm ở đây chứ không rải trong model:

* **Chỉ ``pending`` mới nhận việc được.** Hai máy chạy worker cùng lúc, hoặc một yêu cầu
  được gọi lại vì mất kết nối, đều không được xử lý hai lần.
* **AI sửa kế hoạch rồi thì phiếu XONG; chưa sửa thì mới là "đã trả lời".** Phân biệt hai
  cái này là cách người điều phối biết còn việc gì phải làm tay.
"""

CLAIMABLE_STATES = ('pending',)
OPEN_STATES = ('pending', 'processing', 'answered')


def claimable(state):
    """Worker có được nhận việc phiếu ở trạng thái này không."""
    return state in CLAIMABLE_STATES


def state_after_answer(applied):
    """Trạng thái sau khi AI trả lời. ``applied`` = AI đã sửa kế hoạch nháp xong."""
    return 'done' if applied else 'answered'


def waiting_minutes(created_at, claimed_at, now):
    """Số phút một phiếu nằm chờ worker nhận việc.

    :param created_at: lúc tạo phiếu
    :param claimed_at: lúc worker nhận việc, None nếu chưa ai nhận
    :param now: mốc hiện tại
    :returns: số phút (int) từ lúc tạo tới lúc nhận việc, hoặc tới ``now`` nếu chưa nhận.
        Thiếu ``created_at`` trả None — không đoán.
    """
    if not created_at:
        return None
    end = claimed_at or now
    return int(round((end - created_at).total_seconds() / 60.0))


def is_stale(state, waiting, limit_minutes):
    """Phiếu chờ quá lâu mà chưa ai nhận — dấu hiệu worker đang tắt.

    Chỉ tính phiếu đang chờ: phiếu đã trả lời mà nằm lâu là do người chưa duyệt, không
    phải máy hỏng.
    """
    return bool(state == 'pending' and waiting is not None and waiting >= limit_minutes)
