# utils/ocr_processor.py
import os, json
import cv2
import numpy as np
from pdf2image import convert_from_path
from paddleocr import PaddleOCR
from PIL import Image
import fitz  # PyMuPDF

ocr_model = PaddleOCR(use_angle_cls=True, lang='korean')

def pdf_to_images(pdf_path, image_dir, dpi=200):
    os.makedirs(image_dir, exist_ok=True)
    images = convert_from_path(pdf_path, dpi=dpi)
    image_paths = []
    for idx, img in enumerate(images):
        path = os.path.join(image_dir, f'page_{idx+1}.jpg')
        img.save(path, 'JPEG')
        image_paths.append(path)
    return image_paths

# 🚩 numpy → 파이썬 기본형으로 바꿔 주는 변환기
def to_builtin(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    if isinstance(obj, bytes):
        return obj.decode('utf-8', errors='ignore')
    if isinstance(obj, (list, tuple)):
        return [to_builtin(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_builtin(v) for k, v in obj.items()}
    return obj

def run_ocr(image_paths, output_path):
    result = {}

    for path in image_paths:
        try:
            ocr_result = ocr_model.ocr(path)
            cleaned_result = []

            for line in ocr_result[0]:  # paddleocr는 리스트로 감싼 2차 구조
                box, (text, confidence) = line

                # numpy array를 list로 변환
                if isinstance(box, np.ndarray):
                    box = box.tolist()

                cleaned_result.append({
                    'box': box,
                    'text': text,
                    'confidence': float(confidence)
                })

            result[os.path.basename(path)] = cleaned_result
            print(f"[✅ OCR 성공] {path}")

        except Exception as e:
            print(f"[에러] OCR 실패 - {path}: {str(e)}")
            result[os.path.basename(path)] = {'error': str(e)}

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return output_path

def hybrid_extract(pdf_path, image_dir, output_json_path, min_chars=20, dpi=200):
    """
    PDF에서 하이브리드 추출을 수행합니다.
    - 먼저 내장 텍스트를 추출
    - 텍스트가 부족한 페이지만 OCR 수행
    """
    os.makedirs(os.path.dirname(output_json_path), exist_ok=True)
    
    # PDF 열기
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    
    result = {
        "pdf_path": pdf_path,
        "total_pages": total_pages,
        "min_chars_threshold": min_chars,
        "dpi": dpi,
        "pages": {},
        "ocr_pages_count": 0
    }
    
    ocr_pages = []
    
    # 각 페이지별로 텍스트 추출 시도
    for page_num in range(total_pages):
        page = doc.load_page(page_num)
        
        # 내장 텍스트 추출
        text = page.get_text()
        char_count = len(text.strip())
        
        page_info = {
            "page_number": page_num + 1,
            "char_count": char_count,
            "extraction_method": "text" if char_count >= min_chars else "ocr",
            "text": text if char_count >= min_chars else ""
        }
        
        # 텍스트가 부족하면 OCR 수행
        if char_count < min_chars:
            ocr_pages.append(page_num + 1)
            result["ocr_pages_count"] += 1
            
            # 페이지를 이미지로 변환
            pix = page.get_pixmap(matrix=fitz.Matrix(dpi/72, dpi/72))
            img_path = os.path.join(image_dir, f"page_{page_num + 1}.jpg")
            pix.save(img_path)
            
            # OCR 수행
            try:
                ocr_result = ocr_model.ocr(img_path)
                ocr_text = ""
                ocr_data = []
                
                if ocr_result and ocr_result[0]:
                    for line in ocr_result[0]:
                        box, (text, confidence) = line
                        ocr_text += text + " "
                        ocr_data.append({
                            'box': to_builtin(box),
                            'text': text,
                            'confidence': float(confidence)
                        })
                
                page_info["text"] = ocr_text.strip()
                page_info["ocr_data"] = ocr_data
                page_info["image_path"] = img_path
                
            except Exception as e:
                page_info["error"] = str(e)
                print(f"[에러] OCR 실패 - 페이지 {page_num + 1}: {str(e)}")
        
        result["pages"][f"page_{page_num + 1}"] = page_info
    
    doc.close()
    
    # 결과를 JSON으로 저장
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    return output_json_path, result["ocr_pages_count"]