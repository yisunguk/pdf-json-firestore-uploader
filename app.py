import os
import json
from datetime import datetime
import streamlit as st
import fitz  # PyMuPDF
import pdfplumber

# Firestore 연동
import firebase_admin
from firebase_admin import credentials, firestore

# --- 기본 설정 ---
st.set_page_config(page_title="PDF 텍스트 추출기", layout="centered")
st.title("📄 PDF 텍스트 추출기 (페이지별 JSON 변환 + Firestore 저장)")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- 세션 초기화 ---
for k, v in {"timestamp": None, "json_path": None}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# --- Firestore 초기화 (Streamlit Secrets 기반) ---
if "firebase_app" not in st.session_state:
    try:
        # 이 부분을 try 블록 안에 넣고, print()로 확인
        st.info("Firebase 초기화 시도...")
        firebase_config = {
            "type": st.secrets["firebase"]["type"],
            "project_id": st.secrets["firebase"]["project_id"],
            "private_key_id": st.secrets["firebase"]["private_key_id"],
            "private_key": st.secrets["firebase"]["private_key"].replace('\\n', '\n'),
            "client_email": st.secrets["firebase"]["client_email"],
            "client_id": st.secrets["firebase"]["client_id"],
            "auth_uri": st.secrets["firebase"]["auth_uri"],
            "token_uri": st.secrets["firebase"]["token_uri"],
            "auth_provider_x509_cert_url": st.secrets["firebase"]["auth_provider_x509_cert_url"],
            "client_x509_cert_url": st.secrets["firebase"]["client_x509_cert_url"],
            "universe_domain": st.secrets["firebase"]["universe_domain"]
        }
        st.info(f"Firebase Config - project_id: {firebase_config['project_id']}, client_email: {firebase_config['client_email']}")
        st.info(f"Private Key starts with: {firebase_config['private_key'][:50]}... and ends with: {firebase_config['private_key'][-50:]}")


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


# --- 파일 업로드 및 추출 옵션 ---
uploaded_file = st.file_uploader("PDF 파일을 업로드하세요", type=["pdf"])
extract_method = st.selectbox("텍스트 추출 방식 선택", ["PyMuPDF", "pdfplumber"])

# --- 텍스트 추출 실행 ---
if uploaded_file:
    if not st.session_state.timestamp:
        st.session_state.timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

    filename_base = os.path.splitext(uploaded_file.name)[0]
    temp_pdf = os.path.join(BASE_DIR, f"temp_{st.session_state.timestamp}.pdf")
    json_path = os.path.join(BASE_DIR, "output", "json",
                             f"{filename_base}_text_result_{st.session_state.timestamp}.json")
    os.makedirs(os.path.dirname(json_path), exist_ok=True)

    with open(temp_pdf, "wb") as f:
        f.write(uploaded_file.getbuffer())

    if st.button("🚀 텍스트 추출 실행"):
        try:
            st.info("텍스트 추출 중…")

            result = {
                "pdf_path": temp_pdf,
                "pages": []
            }

            if extract_method == "PyMuPDF":
                doc = fitz.open(temp_pdf)
                for i, page in enumerate(doc):
                    text = page.get_text().strip()
                    result["pages"].append({
                        "page_number": i + 1,
                        "char_count": len(text),
                        "text": text
                    })
                doc.close()

            else:  # pdfplumber
                doc = pdfplumber.open(temp_pdf)
                for i, page in enumerate(doc.pages):
                    text = page.extract_text() or ""
                    result["pages"].append({
                        "page_number": i + 1,
                        "char_count": len(text),
                        "text": text
                    })
                doc.close()

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            st.success("✅ 완료! 결과 JSON 생성됨.")
            with open(json_path, "rb") as f:
                st.download_button("📥 결과 JSON 다운로드", f, file_name=os.path.basename(json_path),
                                   mime="application/json")

            st.session_state.json_path = json_path

        except Exception as e:
            st.error(f"❌ 실패: {e}")

# --- Firestore 저장 기능 ---
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
