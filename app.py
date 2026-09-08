"""Web UI for creating review/incident-video shorts from footage you are licensed to use."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import streamlit as st

from pipeline import DEFAULT_AI_URL, DEFAULT_GEMINI_URL, FlowValidationError, generate_flow, render_parts, validate_flow


EXAMPLE_FLOW = {
    "part1": {
        "hook": {"time": "00:00:10-00:00:18", "has_gunshot": False},
        "sequence": [{"type": "block", "vo_text": "Dispatch logs show a rapidly developing encounter.", "vo_cuts": [["00:00:18", 4], ["00:00:33", 4]], "dialogue_time": "00:00:41-00:00:47", "has_gunshot": False}, {"type": "cliffhanger", "vo_text": "The next decision changes the direction of the scene.", "vo_cuts": [["00:00:50", 5]], "dialogue_time": "00:00:55-00:01:00", "has_gunshot": False}]},
    "part2": {"hook": {"time": "00:01:00-00:01:08", "has_gunshot": False}, "sequence": [{"type": "block", "vo_text": "The report records how responders brought the incident to a close.", "vo_cuts": [["00:01:08", 6]], "dialogue_time": "00:01:15-00:01:21", "has_gunshot": False}]},
}

st.set_page_config(page_title="Case Cut Studio", page_icon="🎬", layout="wide")
st.markdown("""<style>.stApp{background:#0b1020}.hero{padding:1.8rem 0}.eyebrow{color:#f6bd45;font-weight:800;letter-spacing:.16em}.hero h1{font-size:3rem;margin:.3rem 0}.hint{color:#aeb9d5}</style>""", unsafe_allow_html=True)
st.markdown("""<div class="hero"><div class="eyebrow">LICENSED FOOTAGE → TWO-PART SHORTS</div><h1>Case Cut Studio</h1><p class="hint">Cắt footage bạn có quyền sử dụng, thêm voiceover và xuất hai video MP4 dọc. Không dùng để né bản quyền, kiểm duyệt hoặc chính sách nền tảng.</p></div>""", unsafe_allow_html=True)

with st.sidebar:
    st.header("Bộ não AI")
    ai_provider = st.selectbox("Nhà cung cấp AI", ["Gemini", "OpenAI-compatible"])
    ai_key = st.text_input("AI API key", type="password", help="Chỉ dùng trong lần tạo FLOW_DATA hiện tại.")
    ai_model = st.text_input("AI model", "gemini-2.0-flash" if ai_provider == "Gemini" else "gpt-4o-mini")
    ai_url = st.text_input("AI endpoint", DEFAULT_GEMINI_URL if ai_provider == "Gemini" else DEFAULT_AI_URL, help="Với Gemini, giữ {model} để tự chèn tên model.")
    st.header("Kết nối TTS")
    api_key = st.text_input("AI33 API key", type="password", help="Chỉ dùng trong lần dựng hiện tại; không được lưu.")
    voice_id = st.text_input("Voice ID", "elevenlabs_CwhRBWXzGAHq8TQ4Fs17")
    speed = st.number_input("Tốc độ đọc", min_value=0.75, max_value=1.35, value=1.08, step=0.01)

source = st.file_uploader("Video nguồn MP4 (bạn phải có quyền sử dụng)", type=["mp4"])
transcript = st.text_area("Transcript có timestamp (tuỳ chọn, để AI lập FLOW_DATA)", height=140, placeholder="[00:00:10] Nội dung diễn biến...")
if "flow_text" not in st.session_state:
    st.session_state.flow_text = json.dumps(EXAMPLE_FLOW, ensure_ascii=False, indent=2)
if "part1_hook_time" not in st.session_state:
    st.session_state.part1_hook_time = EXAMPLE_FLOW["part1"]["hook"]["time"]
if "part2_hook_time" not in st.session_state:
    st.session_state.part2_hook_time = EXAMPLE_FLOW["part2"]["hook"]["time"]
if st.button("🧠 Tạo FLOW_DATA bằng AI", disabled=not transcript):
    try:
        generated = generate_flow(transcript, 8, ai_key, ai_model, ai_url, ai_provider)
        st.session_state.flow_text = json.dumps(generated, ensure_ascii=False, indent=2)
        st.session_state.part1_hook_time = generated["part1"]["hook"]["time"]
        st.session_state.part2_hook_time = generated["part2"]["hook"]["time"]
        st.success("AI đã tạo FLOW_DATA. Bạn có thể sửa JSON trước khi render.")
    except RuntimeError as error:
        st.error(str(error))
flow_text = st.text_area("FLOW_DATA (JSON)", key="flow_text", height=460)
hook_a, hook_b = st.columns(2)
with hook_a:
    part1_hook_time = st.text_input("Khoảng hook Part 1", key="part1_hook_time", help="Sửa trực tiếp, ví dụ: 00:00:10-00:00:22")
with hook_b:
    part2_hook_time = st.text_input("Khoảng hook Part 2", key="part2_hook_time", help="Sửa trực tiếp, ví dụ: 00:01:00-00:01:12")
col_a, col_b = st.columns([1, 1])
with col_a:
    st.download_button("Tải mẫu FLOW_DATA", json.dumps(EXAMPLE_FLOW, ensure_ascii=False, indent=2), "flow-data-example.json", "application/json")
with col_b:
    st.caption("Sửa trực tiếp mốc bắt đầu và kết thúc hook (2–30 giây). VO luôn tắt audio hiện trường để lời đọc rõ ràng.")

if st.button("🎞️ Render Part 1 & Part 2", type="primary", disabled=not source):
    try:
        flow = json.loads(flow_text)
        flow["part1"]["hook"]["time"] = part1_hook_time
        flow["part2"]["hook"]["time"] = part2_hook_time
        validate_flow(flow)
    except (json.JSONDecodeError, FlowValidationError) as error:
        st.error(f"FLOW_DATA không hợp lệ: {error}")
    else:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "source.mp4"
            input_path.write_bytes(source.getvalue())
            try:
                with st.spinner("Đang cắt clip, tạo voiceover và render…"):
                    outputs = render_parts(input_path, flow, Path(temp_dir), api_key, voice_id, speed)
            except RuntimeError as error:
                st.error(str(error))
            else:
                st.success("Hoàn tất hai part.")
                for name, path in outputs.items():
                    video = path.read_bytes()
                    st.subheader(name.replace("_", " ").title())
                    st.video(video)
                    st.download_button(f"⬇️ Tải {name}.mp4", video, f"{name}.mp4", "video/mp4")
