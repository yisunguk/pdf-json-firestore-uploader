import os
import json
from datetime import datetime
import streamlit as st
import fitz  # PyMuPDF
import pdfplumber

# Firestore 연동
import firebase_admin
from firebase_admin import credentials, firestore

# OpenAI (Azure)
from openai import AzureOpenAI

# --- 기본 설정 ---
st.set_page_config(page_title="PDF 텍스트 추출기", layout="wide")
st.title("📄 PDF 텍스트 추출기 (페이지별 JSON 변환)")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- 세션 초기화 ---
for k, v in {"timestamp": None, "json_path": None}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# --- Firestore 초기화 ---
if "firebase_app" not in st.session_state:
    try:
        if not firebase_admin._apps:
            firebase_config = {
                key: st.secrets["firebase"][key].replace("\\n", "\n") if key == "private_key" else st.secrets["firebase"][key]
                for key in st.secrets["firebase"]
            }
            cred = credentials.Certificate(firebase_config)
            firebase_admin.initialize_app(cred)
        db = firestore.client()
        st.session_state.firebase_app = True
    except Exception as e:
        st.error(f"❌ Firebase 초기화 실패: {e}")
        db = None
else:
    db = firestore.client()

# --- OpenAI API 설정 ---
try:
    openai_client = AzureOpenAI(
        api_key=st.secrets["azure_openai"]["api_key"],
        api_version=st.secrets["azure_openai"]["api_version"],
        azure_endpoint=st.secrets["azure_openai"]["endpoint"]
    )
    openai_deployment = st.secrets["azure_openai"]["deployment"]
except Exception as e:
    openai_client = None
    openai_deployment = None
    st.warning("OpenAI 클라이언트 초기화 실패. AI 분석 기능이 비활성화됩니다.")

# --- 파일 업로드 ---
uploaded_file = st.file_uploader("PDF 파일을 업로드하세요", type=["pdf"])
extract_method = st.selectbox("텍스트 추출 방식 선택", ["PyMuPDF", "pdfplumber"])

# --- 텍스트 추출 실행 ---
if uploaded_file:
    if not st.session_state.timestamp:
        st.session_state.timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

    filename_base = os.path.splitext(uploaded_file.name)[0]
    temp_pdf = os.path.join(BASE_DIR, f"temp_{st.session_state.timestamp}.pdf")
    json_path = os.path.join(BASE_DIR, "output", f"{filename_base}_text_result_{st.session_state.timestamp}.json")
    os.makedirs(os.path.dirname(json_path), exist_ok=True)

    with open(temp_pdf, "wb") as f:
        f.write(uploaded_file.getbuffer())

    if st.button("🚀 텍스트 추출 실행"):
        try:
            result = {"pdf_path": temp_pdf, "pages": []}
            if extract_method == "PyMuPDF":
                doc = fitz.open(temp_pdf)
                result["pages"] = [
                    {"page_number": i+1, "char_count": len(page.get_text()), "text": page.get_text().strip()}
                    for i, page in enumerate(doc)
                ]
                doc.close()
            else:
                doc = pdfplumber.open(temp_pdf)
                result["pages"] = [
                    {"page_number": i+1, "char_count": len(text := (page.extract_text() or "")), "text": text}
                    for i, page in enumerate(doc.pages)
                ]
                doc.close()

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            st.success("✅ 완료! 결과 JSON 생성됨.")
            with open(json_path, "rb") as f:
                st.download_button("📥 결과 JSON 다운로드", f, file_name=os.path.basename(json_path), mime="application/json")
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

# --- Firestore 문서 목록 ---
if db:
    st.markdown("---")
    st.subheader("📂 Firestore 문서 테이블 (문서 삭제 / 저장 / AI 분석)")
    try:
        docs = db.collection("pdf_texts").stream()
        doc_list = [(i+1, doc.id, doc.to_dict()) for i, doc in enumerate(docs)]

        if doc_list:
            for i, doc_id, data in doc_list:
                total_chars = sum(p["char_count"] for p in data.get("pages", []))
                with st.expander(f"📄 문서 미리보기 ({doc_id})"):
                    st.markdown(f"**글자수**: `{total_chars}`  ")
                    for page in data.get("pages", []):
                        st.markdown(f"**📄 Page {page['page_number']}**")
                        st.code(page['text'][:1000] + ("..." if len(page['text']) > 1000 else ""), language="text")

                with st.expander("🧠 AI 분석"):
                    if not openai_client:
                        st.error("OpenAI API 키가 없거나 초기화되지 않았습니다.")
                    else:
                        prompt = st.text_area(f"✍️ 프롬프트 입력", key=f"prompt_{doc_id}")
                        if st.button("🚀 분석 실행", key=f"run_analysis_{doc_id}"):
                            try:
                                full_text = "\n".join([p["text"] for p in data["pages"]])
                                response = openai_client.chat.completions.create(
                                    messages=[
                                        {"role": "system", "content": "You are an assistant that summarizes PDF contents."},
                                        {"role": "user", "content": f"{prompt}\n---\n{full_text[:8000]}"}
                                    ],
                                    model=openai_deployment,
                                    max_tokens=1000,
                                    temperature=0.7,
                                    top_p=1.0
                                )
                                summary = response.choices[0].message.content
                                st.success("✅ 분석 완료")
                                st.markdown(summary)
                            except Exception as e:
                                st.error(f"요약 실패: {e}")

                cols = st.columns([1, 1])
                with cols[0]:
                    if st.button("🗑 삭제", key=f"delete_{doc_id}"):
                        db.collection("pdf_texts").document(doc_id).delete()
                        st.success(f"❌ `{doc_id}` 삭제 완료")
                        st.experimental_rerun()

                with cols[1]:
                    json_string = json.dumps(data, ensure_ascii=False, indent=2)
                    st.download_button("💾 저장", data=json_string, file_name=f"{doc_id}.json", mime="application/json", key=f"download_{doc_id}")

        else:
            st.info("❗ Firestore에 저장된 문서가 없습니다.")

    except Exception as e:
        st.error(f"문서 로딩 실패: {e}")
