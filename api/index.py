# -*- coding: utf-8 -*-
"""위치도 및 현장사진 자동생성 - Vercel 웹 버전 (Flask)"""
import os
import io
import re
import tempfile

import requests
from flask import Flask, request, render_template, send_file, jsonify
from PIL import Image

import hwpx_generator

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KAKAO_JS_KEY = os.environ.get("KAKAO_JS_KEY", "")
KAKAO_REST_KEY = os.environ.get("KAKAO_REST_KEY", "")

TEMPLATE_DIR = os.path.join(BASE_DIR, "template")
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))
# Vercel 요청 본문 한도는 4.5MB. 프론트가 사진을 1200px JPEG로 줄여 보내므로 충분.
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024

STATIC_MAP_URL = "https://dapi.kakao.com/v2/maps/staticmap"


class StaticMapError(Exception):
    pass


def fetch_static_map(center_lat: float, center_lng: float, level: int, width: int, height: int) -> bytes:
    """
    카카오 정적 지도 조회 API로 "베이스 지도"만 받아온다 (마커 없이).
    원(circle)은 카카오 API가 못 그려주므로, 여기서는 순수 지도 이미지만 받고
    draw_circle_on_map()에서 우리가 직접 원을 그려 합성한다.
    scale=1로 명시해서, 브라우저(클라이언트)가 계산한 화면 픽셀 좌표와
    1:1로 정확히 대응되게 한다 (기본값 scale=2를 쓰면 좌표가 2배 어긋남).
    """
    if not KAKAO_REST_KEY:
        raise StaticMapError(
            "KAKAO_REST_KEY가 비어 있습니다. Vercel 환경변수 KAKAO_REST_KEY를 설정하고 다시 배포해주세요."
        )

    headers = {"Authorization": f"KakaoAK {KAKAO_REST_KEY}"}
    params = [
        ("center", f"{center_lng},{center_lat}"),
        ("size", f"{width}x{height}"),
        ("format", "png"),
        ("scale", "1"),
        ("lv", str(max(1, min(15, int(level))))),
    ]

    try:
        resp = requests.get(STATIC_MAP_URL, headers=headers, params=params, timeout=9)
    except requests.exceptions.RequestException as e:
        raise StaticMapError(f"카카오 서버 요청 실패: {e}")
    if resp.status_code != 200:
        raise StaticMapError(
            f"카카오 정적 지도 조회 실패 (상태코드 {resp.status_code}): {resp.text[:300]}"
        )
    return resp.content


def draw_circle_on_map(map_bytes: bytes, px: float, py: float, radius_px: float) -> bytes:
    """
    지도 이미지 위에 빨간 원을 직접 그려서 합성한다.
    px, py: 원 중심의 픽셀 좌표 (지도 이미지 좌상단 기준)
    radius_px: 반경 (픽셀)
    좌표는 브라우저가 카카오 SDK의 실제 투영법(containerPointFromCoords)으로 계산한
    값을 그대로 받은 것이라, 실제 축척과 정확히 일치한다.
    """
    from PIL import ImageDraw

    img = Image.open(io.BytesIO(map_bytes)).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    r = max(4, radius_px)  # 너무 작아서 안 보이는 걸 방지
    bbox = [px - r, py - r, px + r, py + r]
    draw.ellipse(bbox, outline=(255, 0, 0, 235), width=4)

    combined = Image.alpha_composite(img, overlay).convert("RGB")
    buf = io.BytesIO()
    combined.save(buf, format="PNG")
    return buf.getvalue()


@app.route("/")
def index():
    return render_template("index.html", kakao_js_key=KAKAO_JS_KEY)


@app.route("/geocode")
def geocode():
    """
    주소 -> 좌표 변환을 서버가 대신 처리한다 (REST API 키 사용).
    브라우저(카카오 JS SDK)가 직접 검색 API를 호출하지 않게 함으로써,
    페이지 프로토콜(http/https)에 따라 카카오 내부 호출이 실패하던 문제를 피한다.
    """
    query = request.args.get("query", "").strip()
    if not query:
        return jsonify({"error": "검색어가 없습니다."}), 400
    if not KAKAO_REST_KEY:
        return jsonify({"error": "KAKAO_REST_KEY 환경변수가 설정되지 않았습니다."}), 500

    headers = {"Authorization": f"KakaoAK {KAKAO_REST_KEY}"}
    try:
        # 1차: 주소 검색
        resp = requests.get(
            "https://dapi.kakao.com/v2/local/search/address.json",
            headers=headers, params={"query": query}, timeout=8,
        )
        resp.raise_for_status()
        docs = resp.json().get("documents", [])
        if docs:
            d = docs[0]
            return jsonify({"lat": float(d["y"]), "lng": float(d["x"])})

        # 2차: 키워드(장소) 검색으로 재시도
        resp = requests.get(
            "https://dapi.kakao.com/v2/local/search/keyword.json",
            headers=headers, params={"query": query}, timeout=8,
        )
        resp.raise_for_status()
        docs = resp.json().get("documents", [])
        if docs:
            d = docs[0]
            return jsonify({"lat": float(d["y"]), "lng": float(d["x"])})

        return jsonify({"error": "주소를 찾지 못했습니다."}), 404
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"카카오 서버 요청 실패: {e}"}), 502


@app.errorhandler(Exception)
def handle_any_error(e):
    """
    어디서 예외가 나든 항상 JSON으로 응답한다.
    (이게 없으면 Flask가 기본 HTML 에러 페이지를 돌려주고, 프론트엔드는
    그걸 JSON으로 파싱하지 못해서 '알 수 없는 오류'로만 표시됨)
    """
    import traceback
    traceback.print_exc()  # Vercel 로그에 남김
    return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


def _safe_filename(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    for ch in '\\/:*?"<>|':
        text = text.replace(ch, "_")
    return text[:80]


@app.route("/generate", methods=["POST"])
def generate():
    address = request.form.get("address", "").strip()
    photo_file = request.files.get("photo")

    try:
        center_lat = float(request.form.get("center_lat", ""))
        center_lng = float(request.form.get("center_lng", ""))
        level = int(float(request.form.get("level", "3")))
        map_width = int(float(request.form.get("map_width", "700")))
        map_height = int(float(request.form.get("map_height", "400")))
        circle_px_x = float(request.form.get("circle_px_x", ""))
        circle_px_y = float(request.form.get("circle_px_y", ""))
        circle_radius_px = float(request.form.get("circle_radius_px", ""))
    except (TypeError, ValueError):
        return jsonify({"error": "지도 위치 정보가 올바르지 않습니다. 지도를 다시 확인해주세요."}), 400

    if not address:
        return jsonify({"error": "주소를 입력해주세요."}), 400
    if not photo_file or photo_file.filename == "":
        return jsonify({"error": "현장사진을 선택해주세요."}), 400

    with tempfile.TemporaryDirectory() as work_dir:
        try:
            base_map_bytes = fetch_static_map(center_lat, center_lng, level, map_width, map_height)
            map_bytes = draw_circle_on_map(base_map_bytes, circle_px_x, circle_px_y, circle_radius_px)
            map_path = os.path.join(work_dir, "map.png")
            with open(map_path, "wb") as f:
                f.write(map_bytes)

            photo_path = os.path.join(work_dir, "photo_upload")
            photo_file.save(photo_path)

            out_name = f"위치도 및 현장사진({_safe_filename(address)}).hwpx"
            out_path = os.path.join(work_dir, out_name)
            hwpx_generator.generate_hwpx(
                template_dir=TEMPLATE_DIR,
                output_path=out_path,
                address=address,
                map_image_path=map_path,
                photo_image_path=photo_path,
            )

            # 파일을 메모리로 읽어들인 뒤 응답한다.
            # (경로를 직접 send_file에 넘기면, with 블록이 끝나면서 임시폴더를
            #  지우려는 시점에 Windows에서는 아직 응답 스트리밍 중인 파일이
            #  "다른 프로세스가 사용 중"이라며 삭제에 실패하는 문제가 있었음)
            with open(out_path, "rb") as f:
                file_bytes = f.read()

        except StaticMapError as e:
            return jsonify({"error": str(e)}), 502
        except Exception as e:
            return jsonify({"error": f"생성 중 오류가 발생했습니다: {e}"}), 500

    return send_file(
        io.BytesIO(file_bytes),
        as_attachment=True,
        download_name=out_name,
        mimetype="application/octet-stream",
    )
