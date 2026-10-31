# Giám sát Biển Đông

Giao diện web giám sát các đảo, đá, bãi cạn và thực thể trên Biển Đông (Hoàng Sa, Trường Sa...).

## Tính năng
- Bản đồ nền **ảnh vệ tinh** (Esri World Imagery), bản đồ hải dương, OSM; thu phóng tới cấp độ chi tiết công trình.
- ~60 mục tiêu mặc định, tô màu theo bên kiểm soát (VN, TQ chiếm đóng, PH, MY, ĐL, chưa đồn trú).
- Bấm vào mục tiêu (trên bản đồ hoặc danh sách) để xem các tab: **Tổng quan · Tự nhiên · Quân sự · Vị trí · Hình ảnh · Cập nhật**.
  - Vị trí: tọa độ độ-phút-giây & thập phân, khoảng cách tới Cam Ranh, Đà Nẵng, Lý Sơn, đảo Trường Sa (km / hải lý).
  - Hình ảnh: bản đồ vệ tinh trực tiếp, liên kết Google Maps, Sentinel-2 EO Browser, Zoom Earth, NASA Worldview, AMTI; thư viện ảnh tự thêm.
- Tìm kiếm (Việt/Anh/Trung), lọc theo khu vực, loại, bên kiểm soát.
- **Chỉnh sửa / cập nhật**: nút ✏️ Sửa, ➕ Thêm mục tiêu (bấm lên bản đồ), kéo thả để dời vị trí, xóa, tải ảnh từ máy, ghi nhật ký cập nhật có thời gian.
- Dữ liệu chỉnh sửa lưu trong trình duyệt (localStorage); **Xuất/Nhập JSON** để sao lưu, chia sẻ, đồng bộ giữa các máy.

## Chạy
Mở `index.html` bằng trình duyệt, hoặc chạy máy chủ tĩnh:
```bash
python3 -m http.server 8000   # rồi mở http://localhost:8000
```
Có thể triển khai lên GitHub Pages. Cần Internet để tải Leaflet và ảnh vệ tinh.
Mở thẳng một mục tiêu: `index.html#f023` (theo id).

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
Dữ liệu mặc định nằm ở `js/data.js`. Sau khi chỉnh trên giao diện, dùng **Xuất JSON** để lưu; có thể
chép mảng `features` vào `js/data.js` để cập nhật dữ liệu gốc cho mọi người dùng.

> ⚠️ Tọa độ là gần đúng; thông tin quân sự tổng hợp từ nguồn mở, chỉ mang tính tham khảo và cần kiểm chứng.
