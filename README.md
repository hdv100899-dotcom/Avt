# Avt — OSINT Dashboard

Hệ thống tự động thu thập, lưu trữ, chống trùng và phân tích tin quân sự, quốc phòng từ nguồn công khai.
Thiết kế và lộ trình: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Trạng thái

- Giai đoạn 0 xong: schema CSDL, migration, Source Registry, CLI, kiểm thử, CI.
- Giai đoạn 1 đang làm: Collector RSS/Atom (gọi có điều kiện, chu kỳ tự điều chỉnh, lấy toàn văn có
  tôn trọng robots.txt), kho snapshot bất biến, dashboard luồng tin, thống kê độ trễ.
- Giai đoạn 2 (một phần): chống trùng theo URL, nội dung, SimHash; gom nhóm sự kiện, giữ đủ bằng chứng
  và đánh dấu nguồn gốc; dashboard hiển thị theo nhóm.
- Giai đoạn 3: embedding cục bộ (MiniLM đa ngữ) và gom nhóm các bản tin cùng sự kiện khác lời, có ghi
  lý do gộp. Ngưỡng mới được kiểm trên mẫu nhỏ (xem docs/ARCHITECTURE.md mục 5).
- Bộ thu thập `web` (Crawl4AI) cho trang không có RSS hoặc cần JavaScript. Chưa có stealth/proxy.
- **Bộ lọc liên quan quân sự** (không LLM): hồi quy logistic trên embedding sẵn có, huấn luyện từ 605 tin gán
  nhãn tay; dashboard mặc định chỉ hiện tin quân sự, quốc phòng (`/api/groups?scope=military|all|other`).
- **Hơn 130 nguồn, 19 ngôn ngữ** (`config/sources.discovered.json`), tìm bằng `osint source discover`
  (tự phân loại: dùng được / bị chặn / không phải feed / đã chết / cũ, và tự tìm feed trong trang chủ).
- robots.txt **không** chặn thu thập theo mặc định (`OSINT_RESPECT_ROBOTS=1` để bật, hoặc `respect_robots`
  cho từng nguồn). Vẫn giữ khoảng nghỉ 1 giây giữa các yêu cầu tới cùng một trang.
- Chưa có: Telegram, trích xuất thực thể, AI phân tích (LLM), bản tin.

## Chạy thử

```bash
docker compose up -d db                    # PostgreSQL 16 + pgvector
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env && export $(grep -v '^#' .env | xargs)
alembic upgrade head

osint source seed config/sources.en.json          # 14 nguồn tiếng Anh ban đầu (gồm 4 feed SCMP)
osint source seed config/sources.discovered.json  # ~117 nguồn đa ngôn ngữ do công cụ khám phá tìm được
osint source seed config/sources.web.json         # nguồn không RSS (Janes), cần Crawl4AI
osint collect once                         # thu thập một lượt
osint collect run                          # chạy liên tục (kèm nhúng và gom nhóm; --no-embed để tắt)
osint web                                  # dashboard tại http://127.0.0.1:8000
osint stats                                # số tin và độ trễ trung vị theo nguồn
osint dedup                                # gom nhóm các tin chưa có nhóm (tin thu trước GĐ2)
osint cluster                              # nhúng tin mới và gom các bản cùng sự kiện (tải mô hình ~220 MB lần đầu)
osint cluster --reconsider                 # xét lại các tin lẻ sau khi đổi ngưỡng

osint source discover config/candidates.txt --out moi.json   # thăm dò thêm nguồn ứng viên
osint relevance --rescore                  # chấm lại điểm liên quan sau khi huấn luyện lại
osint source add rss https://example.org/feed.xml --name "Example" --language en

# Trang không có RSS (cần: pip install -e ".[crawl]")
osint source add web https://example.org/news/ --name "Example" \
  --config '{"link_selector": "a.story", "link_pattern": "/news/\\d{4}/", "wait_for": "css:a.story"}'
osint source list
```

Dữ liệu snapshot nằm ở `data/` (đổi bằng `OSINT_DATA_DIR`). API: `/api/groups`, `/api/groups/{id}`, `/api/items`, `/api/sources`.

### Chất lượng bộ lọc liên quan

Đo ngoài mẫu trên 103 tin ngẫu nhiên chưa từng dùng để huấn luyện (30 tin quân sự; 56 tin từ 16 ngôn ngữ
khác tiếng Anh): AUROC 0,979 (tiếng Anh 0,962; ngôn ngữ khác 0,993), giữ được 27/30 tin quân sự với độ chính
xác 0,87. Mẫu nhỏ nên khoảng tin cậy rộng; mục tiêu 95% độ phủ khi huấn luyện chưa đạt ngoài mẫu (90%).
Sau đó 130 tin này được đưa vào tập huấn luyện nên cần mẫu kiểm tra mới.

### Giới hạn đã biết

- Một số nguồn trả 403/429 cho client tự động (27 URL trong `config/blocked_sources.json`). Dự án không vượt
  chặn bot, không vượt tường trả phí và không dùng tài khoản giả; các nguồn đó chỉ được ghi nhận.
- Feed `xinhuanet.com/mil` chứa bài cũ năm 2019–2020; `qdnd.vn` chuyển hướng vô hạn từ mạng thử nghiệm.

- **SCMP**: feed chỉ có phần tóm tắt khoảng 500 ký tự mỗi bài (không phải toàn văn); robots.txt yêu cầu
  `Crawl-delay: 10` nên tải toàn văn sẽ rất chậm, và nhiều bài có tường trả phí. Chỉ 14–26% bài trong các
  feed SCMP nhắc đến từ khóa quân sự (đo thô bằng từ khóa), còn lại là tin tổng hợp: cần bộ lọc liên quan.
  Các feed của cùng một tờ báo khai báo chung `publisher` nên không bị tính là nhiều nguồn độc lập.
- **Janes** chưa thu thập: robots.txt của janes.com cấm mọi crawler thường (`User-agent: *` / `Disallow: /`),
  chỉ cho phép các công cụ tìm kiếm nêu tên, trang tin không có RSS, và nội dung chính là sản phẩm trả phí.

- Một số trang (ví dụ Army/Naval/Airforce Technology) chặn client Python bằng 403 dù feed công khai.
  Dự án không giả dạng trình duyệt để né chặn, nên các nguồn này không có trong bộ seed.
- Lần thăm dò đầu tiên của mỗi nguồn lấy cả bài cũ trong feed; `osint stats` bỏ các bài đó khi tính độ trễ.
- Bài trả phí chỉ có đoạn mở đầu trong feed; hệ thống giữ nguyên đoạn đó nếu trang không cho nhiều hơn.

`docker-compose.yml` chưa được chạy thử trong môi trường phát triển (không có Docker daemon);
migration và kiểm thử đã chạy trên PostgreSQL 16 cài trực tiếp.

## Kiểm thử

Test trình duyệt thật chỉ chạy khi `OSINT_TEST_BROWSER=1` (đặt thêm `OSINT_BROWSER_CDP_URL` nếu Playwright
không có sẵn đúng bản Chromium).

Cần một PostgreSQL có extension `vector`. Mặc định kiểm thử kết nối
`postgresql+psycopg://postgres@localhost:5433/postgres` (đổi bằng `OSINT_TEST_ADMIN_URL`);
mỗi lần chạy tạo và xóa cơ sở dữ liệu tạm.

```bash
pytest -q
ruff check . && ruff format --check .
```
