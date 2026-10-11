# -*- coding: utf-8 -*-
"""
hwpx_generator.py
------------------
"위치도 및 현장사진" HWPX 문서를 템플릿 기반으로 자동 생성하는 핵심 모듈.

동작 방식
    1. template/ 폴더(원본 hwpx 압축을 풀어놓은 것)를 임시 폴더로 복사
    2. section0.xml, Preview/PrvText.txt 안의 주소 텍스트를 새 주소로 치환
    3. BinData/image1.bmp(위치도) / image2.bmp(현장사진)를 새 이미지로 교체
       - 원본과 동일한 가로세로비로 센터크롭하여 레이아웃이 틀어지지 않게 함
    4. 다시 zip으로 묶어서 .hwpx로 저장 (mimetype은 무압축 첫 항목 규칙 준수)

주의
    HWPX는 한글과컴퓨터의 공식 스펙 문서를 기준으로 만든 것이 아니라,
    제공된 샘플 파일의 실제 구조를 역공학하여 만든 것입니다.
    한글 버전/문서마다 세부 구조가 다를 수 있으니, 새 템플릿을 쓸 때는
    반드시 실제 한글에서 열어 깨짐이 없는지 확인하세요.
"""

import os
import re
import shutil
import zipfile
import tempfile
from datetime import datetime, timezone
from PIL import Image

# 템플릿에서 실제로 사용된 원본 이미지 픽셀 비율 (가로:세로)
# -> 새 이미지를 이 비율로 센터크롭해서 넣으면 문서 레이아웃(hp:imgDim 등)을
#    건드리지 않고도 비율이 안 틀어짐.
MAP_ASPECT = 47742 / 26078    # 문서에 실제로 표시되는 크기(curSz) 비율 약 1.83:1
PHOTO_ASPECT = 47742 / 26077  # 문서에 실제로 표시되는 크기(curSz) 비율 약 1.83:1

TEMPLATE_ADDRESS_MARKER_RE = re.compile(r'(\[위치도\]\s*)([^<]*?)(</hp:t>)')


def _center_crop_to_aspect(img: Image.Image, target_aspect: float) -> Image.Image:
    """이미지를 지정된 가로세로비로 중앙 기준 크롭한다."""
    w, h = img.size
    current_aspect = w / h
    if current_aspect > target_aspect:
        # 원본이 더 넓다 -> 좌우를 자른다
        new_w = int(h * target_aspect)
        left = (w - new_w) // 2
        box = (left, 0, left + new_w, h)
    else:
        # 원본이 더 좁다(세로로 길다) -> 위아래를 자른다
        new_h = int(w / target_aspect)
        top = (h - new_h) // 2
        box = (0, top, w, top + new_h)
    return img.crop(box)


def _save_as_bmp(src_path: str, dest_path: str, target_aspect: float, max_width: int = 900):
    """이미지를 열어 비율에 맞게 크롭하고(웹 배포용: 응답 4.5MB 제한 때문에 축소) BMP로 저장."""
    with Image.open(src_path) as im:
        im = im.convert("RGB")
        im = _center_crop_to_aspect(im, target_aspect)
        if im.width > max_width:
            im = im.resize((max_width, round(max_width / target_aspect)), Image.LANCZOS)
        im.save(dest_path, format="BMP")


def _replace_address_in_section0(section0_path: str, new_address: str):
    with open(section0_path, "r", encoding="utf-8") as f:
        data = f.read()

    def _sub(m):
        return f"{m.group(1)}{new_address}{m.group(3)}"

    new_data, count = TEMPLATE_ADDRESS_MARKER_RE.subn(_sub, data)
    if count == 0:
        raise ValueError(
            "section0.xml에서 '[위치도] 주소' 패턴을 찾지 못했습니다. "
            "템플릿 구조가 예상과 다릅니다."
        )
    with open(section0_path, "w", encoding="utf-8") as f:
        f.write(new_data)


def _replace_address_in_preview(preview_text_path: str, new_address: str):
    if not os.path.exists(preview_text_path):
        return
    with open(preview_text_path, "r", encoding="utf-8") as f:
        data = f.read()
    data = re.sub(r"(\[위치도\]\s*)([^\r\n>]*)", lambda m: m.group(1) + new_address, data)
    with open(preview_text_path, "w", encoding="utf-8") as f:
        f.write(data)


def _touch_modified_date(content_hpf_path: str):
    if not os.path.exists(content_hpf_path):
        return
    with open(content_hpf_path, "r", encoding="utf-8") as f:
        data = f.read()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = re.sub(
        r'(<opf:meta name="ModifiedDate" content="text">)([^<]*)(</opf:meta>)',
        lambda m: m.group(1) + now_iso + m.group(3),
        data,
    )
    with open(content_hpf_path, "w", encoding="utf-8") as f:
        f.write(data)


def _zip_hwpx(source_dir: str, output_path: str):
    """mimetype을 무압축 첫 항목으로 두고 나머지는 압축하여 zip(.hwpx)으로 묶는다."""
    if os.path.exists(output_path):
        os.remove(output_path)

    mimetype_path = os.path.join(source_dir, "mimetype")

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1) mimetype: 반드시 첫 항목, 무압축
        zf.write(mimetype_path, "mimetype", compress_type=zipfile.ZIP_STORED)

        # 2) 나머지 전부
        for root, _dirs, files in os.walk(source_dir):
            for name in files:
                full_path = os.path.join(root, name)
                arcname = os.path.relpath(full_path, source_dir).replace(os.sep, "/")
                if arcname == "mimetype":
                    continue
                zf.write(full_path, arcname, compress_type=zipfile.ZIP_DEFLATED)


def generate_hwpx(
    template_dir: str,
    output_path: str,
    address: str,
    map_image_path: str,
    photo_image_path: str,
):
    """
    템플릿 기반으로 "위치도 및 현장사진" hwpx 한 개를 생성한다.

    Parameters
    ----------
    template_dir : 압축 풀린 템플릿 폴더 경로 (예: hwpx_tool/template)
    output_path  : 생성될 .hwpx 파일 경로
    address      : 문서에 들어갈 주소 (예: "독서당로22")
    map_image_path  : 위치도(지도) 이미지 파일 경로 (png/jpg 등)
    photo_image_path: 현장사진 이미지 파일 경로 (png/jpg 등)
    """
    with tempfile.TemporaryDirectory() as tmp:
        work_dir = os.path.join(tmp, "work")
        shutil.copytree(template_dir, work_dir)

        # 1. 텍스트 치환
        _replace_address_in_section0(
            os.path.join(work_dir, "Contents", "section0.xml"), address
        )
        _replace_address_in_preview(
            os.path.join(work_dir, "Preview", "PrvText.txt"), address
        )
        _touch_modified_date(os.path.join(work_dir, "Contents", "content.hpf"))

        # 2. 이미지 치환
        _save_as_bmp(
            map_image_path,
            os.path.join(work_dir, "BinData", "image1.bmp"),
            MAP_ASPECT,
        )
        _save_as_bmp(
            photo_image_path,
            os.path.join(work_dir, "BinData", "image2.bmp"),
            PHOTO_ASPECT,
        )

        # 3. 재압축
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        _zip_hwpx(work_dir, output_path)

    return output_path
