import os
import json
from datetime import datetime
import streamlit as st
import fitz  # PyMuPDF
import pdfplumber
from openai import AzureOpenAI

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

# Azure OpenAI 클라이언트 초기화
client = AzureOpenAI(
    api_version=st.secrets["azure_openai"]["api_version"],
    azure_endpoint=st.secrets["azure_openai"]["endpoint"],
    api_key=st.secrets["azure_openai"]["api_key"]
)
deployment = st.secrets["azure_openai"]["deployment"]

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

            else:
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

# --- Firestore 문서 목록 테이블 ---
if db:
    st.markdown("---")
    st.subheader("📂 Firestore 문서 테이블 (문서 삭제 / 저장 / AI 분석 포함)")

    try:
        docs = db.collection("pdf_texts").stream()
        docs = sorted(docs, key=lambda d: d.id, reverse=True)
        for idx, doc in enumerate(docs, start=1):
            doc_id = doc.id
            data = doc.to_dict()
            total_text = "\n".join([page['text'] for page in data.get("pages", [])])
            total_chars = sum([page['char_count'] for page in data.get("pages", [])])

            cols = st.columns([0.3, 0.5, 2.5, 1, 1.2, 1, 1])
            with cols[0]:
                st.markdown(f"**{idx}**")
            with cols[1]:
                st.code(f"{total_chars}", language="")
            with cols[2]:
                st.markdown(f"`{doc_id}`")
            with cols[3]:
                if st.button("📄 미리보기", key=f"preview_{idx}"):
                    st.json(data)
            with cols[4]:
                with st.expander(f"🧠 AI 분석 - {doc_id}", expanded=False):
                    prompt = st.text_area(f"프롬프트 입력 ({doc_id})", key=f"prompt_{idx}", placeholder="예: 문서를 요약하고 핵심 키워드를 알려줘")
                    if st.button("🚀 분석 실행", key=f"analyze_{idx}"):
                        if prompt.strip():
                            with st.spinner("AI 분석 중..."):
                                response = client.chat.completions.create(
                                    model=deployment,
                                    messages=[
                                        {"role": "system", "content": "당신은 문서를 요약하고 분석하는 전문가입니다."},
                                        {"role": "user", "content": f"{prompt}\n\n{total_text}"}
                                    ],
                                    max_tokens=1024,
                                    temperature=0.7
                                )
                                summary = response.choices[0].message.content
                                st.success("✅ 분석 완료")
                                st.markdown("---")
                                st.markdown(f"**AI 분석 결과:**\n\n{summary}")
                        else:
                            st.warning("프롬프트를 입력해주세요.")
            with cols[5]:
                if st.button("🗑 삭제", key=f"delete_{idx}"):
                    db.collection("pdf_texts").document(doc_id).delete()
                    st.warning(f"삭제 완료: {doc_id}")
                    st.experimental_rerun()
            with cols[6]:
                json_filename = f"{doc_id}.json"
                json_str = json.dumps(data, ensure_ascii=False, indent=2)
                st.download_button("💾 저장", json_str, file_name=json_filename, mime="application/json", key=f"dl_{idx}")

    except Exception as e:
        st.error(f"문서 목록 로드 실패: {e}")