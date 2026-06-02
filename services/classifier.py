FIXED_TOPICS_BY_CATEGORY = {
    "Khoa học - Công nghệ": "Khoa học - Công nghệ",
    "Giáo dục": "Giáo dục",
    "Khoa giáo - Khoa học công nghệ": "Khoa học - Giáo dục",
    "Tin tức chung": "Tin tức PTIT",
}

TOPIC_RULES = {
    "Thời sự": [
        "chính phủ",
        "quốc hội",
        "ubnd",
        "hà nội",
        "tp hcm",
        "mưa lớn",
        "ngập",
        "cháy",
        "tai nạn",
        "cứu hộ",
        "dự án",
    ],
    "Kinh doanh": [
        "giá",
        "thị trường",
        "chứng khoán",
        "vn-index",
        "xăng",
        "doanh nghiệp",
        "ngân hàng",
        "lãi suất",
        "bất động sản",
        "đầu tư",
        "tài chính",
    ],
    "Giáo dục": [
        "đại học",
        "học sinh",
        "sinh viên",
        "thi tốt nghiệp",
        "tuyển sinh",
        "giáo dục",
        "điểm chuẩn",
        "du học",
    ],
    "Khoa học - Công nghệ": [
        "ai",
        "trí tuệ nhân tạo",
        "chatgpt",
        "công nghệ",
        "robot",
        "phần mềm",
        "dữ liệu",
        "startup",
        "bán dẫn",
        "điện thoại",
        "khoa học",
    ],
    "Thể thao": [
        "bóng đá",
        "world cup",
        "cầu thủ",
        "hlv",
        "ngoại hạng",
        "tennis",
        "bóng chuyền",
        "sea games",
        "olympic",
    ],
    "Sức khỏe": [
        "bệnh viện",
        "bệnh nhân",
        "sức khỏe",
        "hiến tạng",
        "bác sĩ",
        "thuốc",
        "ung thư",
        "sàng lọc",
        "dịch bệnh",
    ],
    "Pháp luật": [
        "buôn lậu",
        "khởi tố",
        "bị bắt",
        "công an",
        "đường dây",
        "tạm giam",
        "điều tra",
        "truy tố",
        "xét xử",
    ],
    "Giải trí": [
        "ca sĩ",
        "diễn viên",
        "hoa hậu",
        "phim",
        "âm nhạc",
        "nghệ sĩ",
        "showbiz",
        "concert",
    ],
    "Thế giới": [
        "nga",
        "mỹ",
        "trung quốc",
        "ukraine",
        "israel",
        "gaza",
        "châu âu",
        "tổng thống",
        "thủ tướng",
    ],
}


def classify_topic(title, summary, default="Khác"):
    if default in FIXED_TOPICS_BY_CATEGORY:
        return FIXED_TOPICS_BY_CATEGORY[default]

    text = f"{title} {summary}".lower()

    for topic, keywords in TOPIC_RULES.items():
        if any(keyword in text for keyword in keywords):
            return topic

    return default or "Khác"


def classify_news_type(source):
    source_lower = (source or "").lower()

    if "vnexpress" in source_lower:
        return "Báo điện tử"
    if "báo chính phủ" in source_lower or "baochinhphu" in source_lower:
        return "Cổng thông tin Chính phủ"
    if "ptit" in source_lower:
        return "Trang tin trường đại học"
    if "dân trí" in source_lower or "dantri" in source_lower:
        return "Báo điện tử tổng hợp"
    if "24h" in source_lower:
        return "Trang tin tổng hợp"

    return "Không xác định"
