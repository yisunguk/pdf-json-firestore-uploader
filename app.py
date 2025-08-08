import os
import json
from datetime import datetime
import streamlit as st
import fitz  # PyMuPDF
import pdfplumber
import pandas as pd

# Firestore 연동
import firebase_admin
from firebase_admin import credentials, firestore

# --- 기본 설정 ---
st.set_page_config(page_title="PDF 텍스트 추출기", layout="wide")
st.title("📄 PDF 텍스트 추출기 (페이지별 JSON 변환 + Firestore 저장)")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- 세션 초기화 ---
for k, v in {"timestamp": None, "json_path": None}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# --- Firestore 초기화 (Streamlit Secrets 기반) ---
if "firebase_app" not in st.session_state:
    try:
        st.info("Firebase 초기화 시도...")
        firebase_config = {
            k: st.secrets["firebase"][k].replace('\\n', '\n') if k == "private_key" else st.secrets["firebase"][k]
            for k in st.secrets["firebase"]
        }

        if not firebase_admin._apps:
            cred = credentials.Certificate(firebase_config)
            firebase_admin.initialize_app(cred)

        db = firestore.client()
        st.session_state.firebase_app = True

    except Exception as e:
        st.error(f"❌ Firebase 초기화 실패: {e}")
        db = None
else:
    db = firestore.client()

# --- PDF 업로드 및 추출 옵션 ---
uploaded_file = st.file_uploader("PDF 파일을 업로드하세요", type=["pdf"])
extract_method = st.selectbox("텍스트 추출 방식 선택", ["PyMuPDF", "pdfplumber"])

if uploaded_file:
    if not st.session_state.timestamp:
        st.session_state.timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

    filename_base = os.path.splitext(uploaded_file.name)[0]
    temp_pdf = os.path.join(BASE_DIR, f"temp_{st.session_state.timestamp}.pdf")
    json_path = os.path.join(BASE_DIR, "output", "json", f"{filename_base}_text_result_{st.session_state.timestamp}.json")
    os.makedirs(os.path.dirname(json_path), exist_ok=True)

    with open(temp_pdf, "wb") as f:
        f.write(uploaded_file.getbuffer())

    if st.button("🚀 텍스트 추출 실행"):
        try:
            st.info("텍스트 추출 중…")
            result = {"pdf_path": temp_pdf, "pages": []}

            if extract_method == "PyMuPDF":
                with fitz.open(temp_pdf) as doc:
                    for i, page in enumerate(doc):
                        text = page.get_text().strip()
                        result["pages"].append({
                            "page_number": i + 1,
                            "char_count": len(text),
                            "text": text
                        })
            else:
                with pdfplumber.open(temp_pdf) as doc:
                    for i, page in enumerate(doc.pages):
                        text = page.extract_text() or ""
                        result["pages"].append({
                            "page_number": i + 1,
                            "char_count": len(text),
                            "text": text
                        })

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            st.success("✅ 완료! 결과 JSON 생성됨.")
            with open(json_path, "rb") as f:
                st.download_button("📥 결과 JSON 다운로드", f, file_name=os.path.basename(json_path), mime="application/json")

            st.session_state.json_path = json_path

        except Exception as e:
            st.error(f"❌ 실패: {e}")

# --- Firestore에 저장 ---
if st.session_state.json_path and db:
    st.info("💾 JSON을 Firestore에 저장할 수 있습니다.")
    if st.button("📤 Firestore에 저장"):
        try:
            with open(st.session_state.json_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)

            doc_name = f"{filename_base}_{st.session_state.timestamp}"
            db.collection("pdf_texts").document(doc_name).set(json_data)
            st.success(f"✅ Firestore 저장 완료: {doc_name}")

        except Exception as e:
            st.error(f"Firestore 저장 실패: {e}")

# --- Firestore 문서 테이블 ---
st.markdown("---")
st.subheader("📂 문서 테이블")

try:
    docs = db.collection("pdf_texts").stream()
    doc_list = []

    for i, doc in enumerate(docs, start=1):
        doc_id = doc.id
        data = doc.to_dict()
        total_chars = sum(p.get("char_count", 0) for p in data.get("pages", []))
        first_text = data["pages"][0]["text"] if data.get("pages") else ""
        preview = first_text[:100] + "..." if len(first_text) > 100 else first_text

        doc_list.append({
            "index": i,
            "doc_id": doc_id,
            "char_count": total_chars,
            "preview": preview,
            "full_data": data
        })

    if doc_list:
        # 테이블 헤더 출력
        st.markdown(
            """
            <style>
                .header-row {
                    display: flex;
                    font-weight: bold;
                    padding: 0.25rem 0;
                    border-bottom: 1px solid #ccc;
                }
                .header-row > div {
                    flex: 1;
                    text-align: center;
                }
            </style>
            <div class='header-row'>
                <div style='flex:0.5'>선택</div>
                <div style='flex:0.5'>#</div>
                <div style='flex:1'>글자 수</div>
                <div style='flex:2'>문서 제목</div>
                <div style='flex:3'>미리보기</div>
                <div style='flex:1'>삭제</div>
                <div style='flex:1'>저장</div>
            </div>
            """,
            unsafe_allow_html=True
        )

        for doc in doc_list:
            col1, col2, col3, col4, col5, col6, col7 = st.columns([0.5, 0.5, 1, 2, 3, 1, 1])

            with col1:
                st.checkbox("", key=f"chk_{doc['doc_id']}")
            with col2:
                st.markdown(f"<span style='font-size:14px;'>{doc['index']}</span>", unsafe_allow_html=True)
            with col3:
                st.markdown(f"<span style='font-size:14px;'>{doc['char_count']}</span>", unsafe_allow_html=True)
            with col4:
                st.markdown(f"<span style='font-size:14px;'>{doc['doc_id']}</span>", unsafe_allow_html=True)
            with col5:
                with st.expander("📄 문서 미리보기"):
                    for page in doc["full_data"].get("pages", []):
                        st.markdown(f"**페이지 {page['page_number']}**")
                        st.write(page["text"])
            with col6:
                if st.button("🗑 삭제", key=f"del_{doc['doc_id']}"):
                    db.collection("pdf_texts").document(doc["doc_id"]).delete()
                    st.warning(f"❌ `{doc['doc_id']}` 삭제 완료 (새로고침 필요)")
            with col7:
                json_data = json.dumps(doc["full_data"], ensure_ascii=False, indent=2)
                st.download_button("💾 저장", data=json_data, file_name=f"{doc['doc_id']}.json", mime="application/json", key=f"save_{doc['doc_id']}")

    else:
        st.info("📭 Firestore에 저장된 문서가 없습니다.")

except Exception as e:
    st.error(f"문서 로딩 실패: {e}")