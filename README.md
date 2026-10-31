# Giám sát Biển Đông

Giao diện web giám sát các đảo, đá, bãi cạn và thực thể trên Biển Đông (Hoàng Sa, Trường Sa...).

## Tính năng
- Bản đồ nền **ảnh vệ tinh** (Esri World Imagery), bản đồ hải dương, OSM; thu phóng tới cấp độ chi tiết công trình.
- ~90 mục tiêu mặc định (đảo, đá, bãi cạn, bãi ngầm, nhà giàn DK1, các cụm/nhóm đảo có vẽ phạm vi), tô màu theo bên kiểm soát (VN, TQ chiếm đóng, PH, MY, ĐL, chưa đồn trú).
- Bấm vào mục tiêu (trên bản đồ hoặc danh sách) để xem các tab: **Tổng quan · Tự nhiên · Quân sự · Vị trí · Hình ảnh · Cập nhật**.
  - Vị trí: tọa độ độ-phút-giây & thập phân, khoảng cách tới Cam Ranh, Đà Nẵng, Lý Sơn, đảo Trường Sa (km / hải lý).
  - Hình ảnh: bản đồ vệ tinh trực tiếp, liên kết Google Maps, Sentinel-2 EO Browser, Zoom Earth, NASA Worldview, AMTI; thư viện ảnh tự thêm.
- Tìm kiếm (Việt/Anh/Trung), lọc theo khu vực, loại, bên kiểm soát.
- **Chỉnh sửa / cập nhật**: nút ✏️ Sửa, ➕ Thêm mục tiêu (bấm lên bản đồ), kéo thả để dời vị trí, xóa, tải ảnh từ máy, ghi nhật ký cập nhật có thời gian.
- Dữ liệu chỉnh sửa lưu trong trình duyệt (localStorage); **Xuất/Nhập JSON** để sao lưu, chia sẻ, đồng bộ giữa các máy.

## Tin tức tự động
- Workflow `.github/workflows/news.yml` chạy **mỗi 2 giờ** (và có thể bấm chạy tay ở tab *Actions → Cập nhật tin tức Biển Đông → Run workflow*).
- Script `scripts/fetch_news.py` chỉ thu thập **tin tiếng Anh** (báo chí quốc tế) qua Google News: truy vấn chung
  + truy vấn tự sinh theo tên tiếng Anh của từng thực thể trong `js/data.js`; bài chỉ khớp tên thực thể phải có ngữ cảnh
  Biển Đông; loại tin thời tiết; ghi vào `data/news.json` (giữ 45 ngày, tối đa 800 bài).
- Ứng dụng đọc `data/news.json`, tự gắn bài báo vào thực thể được nhắc tên (Việt/Anh/Trung + “Từ khóa tin tức” tự thêm khi sửa mục tiêu):
  - Nút **📰 Tin tức**: danh sách tin, lọc theo thời gian, ngôn ngữ, tìm kiếm; số đỏ = số tin trong 24 giờ.
  - Tab **Tin tức** trong từng mục tiêu + liên kết tìm ngay trên Google News; mục “Tin chung về quần đảo”.
  - Mục tiêu có tin trong 72 giờ qua nhấp nháy viền cam trên bản đồ.
- **Lưu ý**: lịch chạy tự động của GitHub Actions chỉ hoạt động khi workflow nằm trên nhánh mặc định (`main`).
- Chạy thử tại máy: `python3 scripts/fetch_news.py`.

## Chạy
Mở `index.html` bằng trình duyệt, hoặc chạy máy chủ tĩnh:
```bash
python3 -m http.server 8000   # rồi mở http://localhost:8000
```
Có thể triển khai lên GitHub Pages. Cần Internet để tải Leaflet và ảnh vệ tinh.
Mở thẳng một mục tiêu: `index.html#f023` (theo id).

## Bản HTML ngoại tuyến (một file, không cần web / Internet)
```bash
python3 scripts/build_offline.py      # → dist/bien-dong-offline.html (~15 MB)
```
- Nhúng sẵn: Leaflet, giao diện, dữ liệu thực thể, tin tức (bản chụp lúc tạo file) và **ảnh vệ tinh Sentinel-2 cloudless 10 m**
  (EOX, CC BY-NC-SA 4.0 – chỉ dùng phi thương mại): toàn khu vực ở zoom 2–8, quanh từng thực thể ở zoom 10–14.
- Tùy chọn: `--ring 3` (vùng chi tiết rộng hơn), `--year 2023`, `--detail-zoom 13` (file nhỏ hơn).
- Thư mục `dist/`, `.tilecache/` không đưa lên Git.
- iPad: chép file vào app Tệp rồi mở bằng ứng dụng có trình duyệt chạy được JavaScript (VD *Documents by Readdle*);
  máy tính: bấm đúp để mở bằng trình duyệt.

## Mở trên iPad
Giao diện đã tối ưu cho iPad (dọc: nút ☰ mở danh sách, bảng thông tin trượt từ dưới; ngang: đầy đủ).
Cần đưa trang lên một địa chỉ web (repo đang private nên GitHub Pages bản miễn phí không dùng được):

**Cách 1 – Vercel (miễn phí, dùng được repo private, làm ngay trên iPad bằng Safari)**
1. Vào https://vercel.com → *Sign up / Continue with GitHub*.
2. *Add New… → Project* → chọn repo `Avt` → *Import* (cấp quyền nếu được hỏi).
3. Framework Preset: **Other**; không cần lệnh build → *Deploy*.
4. Nhận địa chỉ dạng `https://avt-xxx.vercel.app`. Mỗi lần đẩy code lên nhánh chính, trang tự cập nhật.
   (Muốn triển khai nhánh khác: *Settings → Git → Production Branch*.)
   Cloudflare Pages (pages.cloudflare.com) làm tương tự.

**Cách 2 – GitHub Pages**: chuyển repo sang Public (hoặc dùng GitHub Pro) → *Settings → Pages* →
*Deploy from a branch* → chọn nhánh, thư mục `/ (root)` → địa chỉ `https://hdv100899-dotcom.github.io/Avt/`.

**Trên iPad**: mở địa chỉ bằng Safari → nút Chia sẻ → **Thêm vào MH chính** để dùng toàn màn hình như ứng dụng.
Lưu ý dữ liệu sửa lưu riêng trong Safari của iPad; dùng ⬇️ Xuất JSON (lưu vào app Tệp) / ⬆️ Nhập JSON để đồng bộ với máy khác.

## Cập nhật dữ liệu gốc
Thêm thực thể mới vào **cuối** mảng trong `js/data.js` (để giữ nguyên id cũ) và tăng `DEFAULT_DATA_REV`;
trình duyệt đã lưu dữ liệu cũ sẽ tự bổ sung thực thể mới mà không mất phần đã chỉnh sửa.
Dữ liệu mặc định nằm ở `js/data.js`. Sau khi chỉnh trên giao diện, dùng **Xuất JSON** để lưu; có thể
chép mảng `features` vào `js/data.js` để cập nhật dữ liệu gốc cho mọi người dùng.

> ⚠️ Tọa độ là gần đúng; thông tin quân sự tổng hợp từ nguồn mở, chỉ mang tính tham khảo và cần kiểm chứng.
