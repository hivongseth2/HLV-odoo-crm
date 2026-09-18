"""So kế hoạch với thực tế — hàm thuần, vào gì ra nấy.

Vòng đối chiếu là chỗ tri thức được sinh ra: kế hoạch nói "tới lúc 9:10", thực tế nói
"9:37", và chênh lệch lặp lại đủ nhiều lần thì định mức của cụm đó sai chứ không phải hôm
đó xui. Không đo thì mọi định mức mãi mãi là con số đoán ban đầu.

Nguyên tắc: **không suy số thực tế từ kế hoạch.** Hai nguồn phải độc lập, trộn vào nhau là
mất khả năng đối chiếu.

Không đụng ``self.env``, không ghi gì, không gọi mạng.
"""

# Chênh trong ngưỡng này coi như đúng hẹn. 15 phút là mức mà người điều phối không buồn
# nhắc tới — nhỏ hơn thì mọi chuyến đều "lệch" và cảnh báo mất hết ý nghĩa.
ON_TIME_TOLERANCE_MINUTES = 15


def minutes_between(earlier, later):
    """Số phút từ ``earlier`` tới ``later``, làm tròn. None nếu thiếu một trong hai.

    Giá trị âm nghĩa là ``later`` xảy ra TRƯỚC — giữ nguyên dấu, vì "tới sớm 20 phút" là
    một thông tin khác hẳn "tới muộn 20 phút".
    """
    if not earlier or not later:
        return None
    return int(round((later - earlier).total_seconds() / 60.0))


def leg_variance(planned_offsets, actual_offsets):
    """Ghép giờ dự kiến với giờ thực tế theo thứ tự ghé.

    :param planned_offsets: list phút-từ-lúc-xuất-phát theo kế hoạch, None nếu không tính được
    :param actual_offsets: list phút-từ-lúc-xuất-phát đo được, None nếu điểm đó không có dấu vết
    :returns: list dict ``{'planned', 'actual', 'variance', 'on_time'}`` cùng độ dài với
        ``planned_offsets``. ``variance`` dương = thực tế CHẬM hơn kế hoạch.
        Thiếu một vế thì ``variance`` và ``on_time`` đều None — không đoán.
    """
    result = []
    for index, planned in enumerate(planned_offsets):
        actual = actual_offsets[index] if index < len(actual_offsets) else None
        if planned is None or actual is None:
            result.append({'planned': planned, 'actual': actual,
                           'variance': None, 'on_time': None})
            continue
        variance = actual - planned
        result.append({
            'planned': planned,
            'actual': actual,
            'variance': variance,
            'on_time': abs(variance) <= ON_TIME_TOLERANCE_MINUTES,
        })
    return result


def summarize_variance(items):
    """Tóm tắt một list kết quả của ``leg_variance``.

    Trả về dict::

        {'measured': int,        # số điểm đối chiếu được
         'on_time': int,         # số điểm trong ngưỡng
         'late': int, 'early': int,
         'mean_variance': int|None,      # chênh trung bình, giữ dấu
         'mean_abs_variance': int|None,  # sai số trung bình, bỏ dấu
         'worst': dict|None}             # điểm lệch nhiều nhất

    ``mean_variance`` giữ dấu để thấy ĐỊNH MỨC lệch về một phía (luôn chậm = định mức quá
    lạc quan); ``mean_abs_variance`` bỏ dấu để thấy mức DAO ĐỘNG. Hai con số nói hai điều
    khác nhau và cả hai đều cần: định mức đúng trung bình mà dao động lớn thì vẫn không
    hứa giờ với khách được.

    List rỗng hoặc không điểm nào đối chiếu được trả về ``measured = 0`` và các trung bình
    là None — không trả 0, vì 0 nghĩa là "đo được và đúng y hẹn".
    """
    measured = [item for item in items if item.get('variance') is not None]
    if not measured:
        return {'measured': 0, 'on_time': 0, 'late': 0, 'early': 0,
                'mean_variance': None, 'mean_abs_variance': None, 'worst': None}
    variances = [item['variance'] for item in measured]
    return {
        'measured': len(measured),
        'on_time': sum(1 for item in measured if item['on_time']),
        'late': sum(1 for value in variances if value > ON_TIME_TOLERANCE_MINUTES),
        'early': sum(1 for value in variances if value < -ON_TIME_TOLERANCE_MINUTES),
        'mean_variance': int(round(sum(variances) / len(variances))),
        'mean_abs_variance': int(round(sum(abs(value) for value in variances) / len(variances))),
        'worst': max(measured, key=lambda item: abs(item['variance'])),
    }


def measured_leg_minutes(offsets):
    """Từ giờ tới cộng dồn -> thời lượng từng chặng.

    Chặng đầu là chính ``offsets[0]`` (tính từ lúc xuất phát). Chặng sau là hiệu hai mốc
    liên tiếp CÓ ĐO ĐƯỢC — điểm thiếu dấu vết bị bỏ qua chứ không tính là 0 phút, và chặng
    bắc qua nó được đánh dấu ``spans`` > 1 để bên gọi biết đó là tổng của nhiều chặng.

    :returns: list dict ``{'index', 'minutes', 'spans'}``
    """
    legs = []
    previous_index, previous_value = None, 0
    for index, value in enumerate(offsets):
        if value is None:
            continue
        legs.append({
            'index': index,
            'minutes': value - previous_value,
            'spans': index - previous_index if previous_index is not None else index + 1,
        })
        previous_index, previous_value = index, value
    return legs
