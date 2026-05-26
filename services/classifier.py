TOPIC_RULES = {
    "Thời sự": [
        "chính phủ", "quốc hội", "bộ quốc phòng", "ubnd", "hà nội", "tp hcm",
        "mưa lớn", "ngập", "cháy", "tai nạn", "cứu hộ", "dự án", "giải phóng mặt bằng"
    ],
    "Kinh doanh": [
        "giá", "thị trường", "chứng khoán", "vn-index", "xăng", "doanh nghiệp",
        "ngân hàng", "lãi suất", "bất động sản", "đầu tư", "tài chính"
    ],
    "Giáo dục": [
        "đại học", "học sinh", "sinh viên", "thi tốt nghiệp", "tuyển sinh",
        "giáo dục", "điểm chuẩn", "du học"
    ],
    "Công nghệ": [
        "ai", "trí tuệ nhân tạo", "chatgpt", "công nghệ", "robot", "phần mềm",
        "dữ liệu", "startup", "bán dẫn", "điện thoại"
    ],
    "Thể thao": [
        "bóng đá", "world cup", "cầu thủ", "hlv", "ngoại hạng", "tennis",
        "bóng chuyền", "sea games", "olympic"
    ],
    "Sức khỏe": [
        "bệnh viện", "bệnh nhân", "sức khỏe", "hiến tạng", "bác sĩ", "thuốc",
        "ung thư", "sàng lọc", "dịch bệnh"
    ],
    "Pháp luật": [
        "buôn lậu", "khởi tố", "bị bắt", "công an", "đường dây", "tạm giam",
        "điều tra", "truy tố", "xét xử"
    ],
    "Giải trí": [
        "ca sĩ", "diễn viên", "hoa hậu", "phim", "âm nhạc", "nghệ sĩ",
        "showbiz", "concert"
    ],
    "Thế giới": [
        "nga", "mỹ", "trung quốc", "ukraine", "israel", "gaza", "châu âu",
        "tổng thống", "thủ tướng"
    ],
}


def classify_topic(title, summary, default="Khác"):
    text = f"{title} {summary}".lower()

    for topic, keywords in TOPIC_RULES.items():
        if any(keyword in text for keyword in keywords):
            return topic

    return default or "Khác"


def classify_news_type(source):
    source = source.lower()

    if "vnexpress" in source:
        return "Báo điện tử tổng hợp"
    if "dân trí" in source or "dantri" in source:
        return "Báo điện tử tổng hợp"
    if "24h" in source:
        return "Trang tin tổng hợp"

    return "Không xác định"
