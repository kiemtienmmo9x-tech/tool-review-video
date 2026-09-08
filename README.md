# Case Cut Studio

Ứng dụng Streamlit dựng hai video MP4 dọc từ footage mà bạn có quyền sử dụng và cấu trúc `FLOW_DATA` JSON. Bạn có thể dán transcript có timestamp để API AI tạo bản nháp `FLOW_DATA`, sau đó tự sửa JSON trước khi render.

## Chạy local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Máy chạy cần có **FFmpeg** trong `PATH`. Mở đường dẫn Streamlit hiển thị trong terminal, tải video MP4, dán transcript hoặc `FLOW_DATA`, chọn **Gemini** hoặc endpoint tương thích OpenAI, nhập khoá AI và khoá AI33, rồi chọn **Render Part 1 & Part 2**. Hai ô **Khoảng hook Part 1/2** cho phép bạn sửa trực tiếp thời điểm bắt đầu và kết thúc (từ 2–30 giây), ví dụ `00:00:10-00:00:22`.

## Lưu ý sử dụng có trách nhiệm

Chỉ dùng video, nhạc và tư liệu mà bạn có quyền sử dụng. Công cụ không hỗ trợ thay đổi audio để né nhận diện bản quyền, kiểm duyệt hoặc chính sách nền tảng. Khi có voiceover, âm thanh hiện trường được thay thế hoàn toàn để lời đọc rõ ràng; audio thoại còn lại chỉ được chuẩn hoá loudness.
