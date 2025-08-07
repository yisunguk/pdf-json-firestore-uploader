# app.py

import os
from datetime import datetime
import streamlit as st
from utils.ocr_processor import hybrid_extract

st.set_page_config(page_title="한글 PDF 하이브리드 추출기", layout="centered")
st.title("📄 한글 PDF 하이브리드 추출기 (텍스트 + 필요한 페이지만 OCR)")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

for k, v in {"timestamp": None, "json_path": None}.items():
    if k not in st.session_state:
        st.session_state[k] = v

uploaded_file = st.file_uploader("PDF 파일을 업로드하세요", type=["pdf"])
min_chars = st.number_input("OCR 전환 기준(한 페이지 텍스트 글자 수)", min_value=0, value=20, step=5)
dpi = st.slider("OCR 대상 페이지 이미지 DPI", min_value=120, max_value=300, value=200, step=10)

if uploaded_file:
    if not st.session_state.timestamp:
        st.session_state.timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

    temp_pdf = os.path.join(BASE_DIR, f"temp_{st.session_state.timestamp}.pdf")
    with open(temp_pdf, "wb") as f:
        f.write(uploaded_file.getbuffer())

    image_dir = os.path.join(BASE_DIR, "output", "images", st.session_state.timestamp)
  # 업로드된 파일 이름 추출 (확장자 제거)
    filename_base = os.path.splitext(uploaded_file.name)[0]

# 새로운 JSON 경로
    json_path = os.path.join(BASE_DIR, "output", "json",
                         f"{filename_base}_hybrid_result_{st.session_state.timestamp}.json")


    if st.button("🚀 하이브리드 추출 실행"):
        try:
            st.info("진행 중… (내장 텍스트 → OCR 대상 판별 → 대상 페이지만 OCR)")
            saved_path, ocr_pages = hybrid_extract(
                pdf_path=temp_pdf,
                image_dir=image_dir,
                output_json_path=json_path,
                min_chars=min_chars,
                dpi=dpi,
            )
            st.success(f"완료! OCR 수행 페이지 수: {ocr_pages}")
            st.caption(f"JSON 경로: {saved_path}")
            with open(saved_path, "rb") as f:
                st.download_button("📥 결과 JSON 다운로드", f, file_name=os.path.basename(saved_path), mime="application/json")
            st.session_state.json_path = saved_path
        except Exception as e:
            st.error(f"실패: {e}")

if st.session_state.json_path:
    st.info("최근 생성된 결과 JSON")
    st.code(st.session_state.json_path)
