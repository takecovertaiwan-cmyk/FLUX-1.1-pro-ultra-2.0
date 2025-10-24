# ====================================================================
# [A] WesmartAI 證據報告 Web App (final_definitive_flow + 完整備註版)
# 作者: Gemini & User
# 說明: 此版本保留原有功能，僅新增索引與備註。
# --------------------------------------------------------------------
# [A1] 核心功能流程
# 1. 使用者多次生成預覽 (API: /generate)
# 2. 結束任務並封存證據 (API: /finalize_session)
# 3. 生成 PDF 報告 (API: /create_report)
# --------------------------------------------------------------------
# [A2] 系統特性
# - 整合 FLUX API (Black-Forest-Labs)
# - 全程以 SHA-256 驗證雜湊鏈結
# - 可離線驗證 JSON 與 PDF 對應一致性
# ====================================================================

# === B1. 套件匯入 ===
import requests, json, hashlib, uuid, datetime, random, time, os, io, base64
from flask import Flask, render_template, request, jsonify, send_from_directory, url_for
from PIL import Image
from fpdf import FPDF
from fpdf.enums import XPos, YPos
import qrcode

# === B2. 讀取環境變數 ===
# 用於後端呼叫 FLUX API，需設定 BFL_API_KEY
API_key = os.getenv("BFL_API_KEY")

# === B3. Flask 初始化 ===
app = Flask(__name__)
static_folder = 'static'
if not os.path.exists(static_folder): os.makedirs(static_folder)
app.config['UPLOAD_FOLDER'] = static_folder

# === C1. 工具函式 ===
import json, hashlib

def sha256_bytes(b: bytes) -> str:
    """回傳資料的 SHA256 雜湊值 (hex 字串)"""
    return hashlib.sha256(b).hexdigest()

def sha256_text(s: str) -> str:
    """將文字轉為 UTF-8 bytes 並回傳 SHA256 雜湊"""
    return sha256_bytes(s.encode("utf-8"))

def compute_image_hash_from_b64(b64_str: str) -> str:
    """針對 Base64 圖片內容計算雜湊"""
    return sha256_text(b64_str)

def compute_step_hash(ts_iso: str, img_b64: str, prompt: str, seed: int) -> dict:
    """
    計算四重雜湊 + Step Hash
    輸入：
        ts_iso  - 時間戳記字串 (ISO 格式)
        img_b64 - 圖片 base64 字串
        prompt  - 提示詞
        seed    - 隨機種子
    輸出：
        dict，包含四重雜湊與組合後的 step_hash
    """
    ts_hash     = sha256_text(ts_iso)
    img_hash    = compute_image_hash_from_b64(img_b64)
    prompt_hash = sha256_text(prompt or "")
    seed_hash   = sha256_text(str(seed))

    # 四重雜湊整合為 step_hash（順序固定）
    payload = json.dumps(
        {
            "timestamp_hash": ts_hash,
            "image_hash": img_hash,
            "prompt_hash": prompt_hash,
            "seed_hash": seed_hash
        },
        sort_keys=True, ensure_ascii=False
    )
    step_hash = sha256_text(payload)

    return {
        "timestamp_hash": ts_hash,
        "image_hash": img_hash,
        "prompt_hash": prompt_hash,
        "seed_hash": seed_hash,
        "step_hash": step_hash
    }

# === C2. PDF 報告類別 ===
from fpdf import FPDF
from fpdf.enums import XPos, YPos
import os, qrcode

class WesmartPDFReport(FPDF):
    """生成 PDF 報告，包含封面、細節、驗證頁。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # C2-1. 字型下載與設定
        if not os.path.exists("NotoSansTC.otf"):
            print("下載中文字型...")
            try:
                import requests
                r = requests.get(
                    "https://github.com/googlefonts/noto-cjk/raw/main/Sans/OTF/TraditionalChinese/NotoSansCJKtc-Regular.otf"
                )
                r.raise_for_status()
                with open("NotoSansTC.otf", "wb") as f:
                    f.write(r.content)
            except Exception as e:
                print(f"字型下載失敗: {e}")
        self.add_font("NotoSansTC", "", "NotoSansTC.otf")
        self.set_auto_page_break(auto=True, margin=25)
        self.alias_nb_pages()
        self.logo_path = "LOGO.jpg" if os.path.exists("LOGO.jpg") else None

    # === C2-2. 頁首 (Header) ===
    def header(self):
        if self.logo_path:
            with self.local_context(fill_opacity=0.08, stroke_opacity=0.08):
                img_w = 120
                self.image(self.logo_path, x=(self.w - img_w) / 2, y=(self.h - img_w) / 2, w=img_w)
        if self.page_no() > 1:
            self.set_font("NotoSansTC", "", 9)
            self.set_text_color(128)
            self.cell(0, 10, "WesmartAI 生成式 AI 證據報告", new_x=XPos.LMARGIN, new_y=YPos.TOP, align='L')

    # === C2-3. 頁尾 (Footer) ===
    def footer(self):
        self.set_y(-15)
        self.set_font("NotoSansTC", "", 8)
        self.set_text_color(128)
        self.cell(0, 10, f"第 {self.page_no()}/{{nb}} 頁", align="C")

    # === C2-4. 章節標題 ===
    def chapter_title(self, title):
        self.set_font("NotoSansTC", "", 16)
        self.cell(0, 12, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")

    # === C2-5. 章節內文 ===
    def chapter_body(self, content):
        self.set_font("NotoSansTC", "", 10)
        self.multi_cell(0, 7, str(content), align="L")

    # === C2-6. 封面頁 ===
    def create_cover(self, meta):
        self.add_page()
        if self.logo_path:
            self.image(self.logo_path, x=(self.w - 60) / 2, y=25, w=60)
        self.set_y(100)
        self.set_font("NotoSansTC", "", 28)
        self.cell(0, 20, "WesmartAI 證據報告", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")

        data = [
            ("出證申請人:", meta.get("applicant", "N/A")),
            ("申請出證時間:", meta.get("issued_at", "N/A")),
            ("報告編號:", meta.get("report_id", "N/A")),
            ("出證單位:", meta.get("issuer", "N/A")),
        ]
        for label, value in data:
            self.set_font("NotoSansTC", "", 12)
            self.cell(45, 10, label, align="L")
            self.multi_cell(0, 10, str(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")

    # === C2-7. 生成任務細節頁 ===
    def create_generation_details_page(self, proof_data):
        self.add_page()
        self.chapter_title("一、生成任務基本資訊")

        # 防呆檢查
        if not proof_data.get("event_proof") or not proof_data["event_proof"].get("snapshots"):
            self.chapter_body("⚠️ 無法載入封存資料。請確認 finalize_session 是否執行成功。")
            return

        snapshots = proof_data["event_proof"]["snapshots"]
        self.chapter_body(f"版本數：{len(snapshots)}")

        self.chapter_title("二、各版本快照與雜湊資訊")
        for snap in snapshots:
            self.chapter_body(f"版本索引：{snap.get('version_index', 'N/A')}")
            self.chapter_body(f"時間戳記(UTC)：{snap.get('timestamp_utc', 'N/A')}")
            self.chapter_body(f"Prompt：{snap.get('prompt', 'N/A')}")
            self.chapter_body(f"Seed：{snap.get('seed', 'N/A')}")
            self.chapter_body(f"時間戳雜湊 (timestamp_hash)：{snap.get('timestamp_hash', 'N/A')}")
            self.chapter_body(f"圖片雜湊 (image_hash)：{snap.get('image_hash', 'N/A')}")
            self.chapter_body(f"提示詞雜湊 (prompt_hash)：{snap.get('prompt_hash', 'N/A')}")
            self.chapter_body(f"種子雜湊 (seed_hash)：{snap.get('seed_hash', 'N/A')}")
            self.chapter_body(f"Step Hash (step_hash)：{snap.get('step_hash', 'N/A')}")
            self.chapter_body(" ")

    # === C2-8. 驗證頁 ===
    def create_conclusion_page(self, proof_data):
        self.add_page()
        self.chapter_title("三、報告驗證")

        desc = (
            "本報告之真實性與完整性，係依據每一生成頁面所記錄之四重雜湊"
            "（時間戳雜湊、圖片雜湊、提示詞雜湊與種子雜湊）逐步累積計算所得。\n"
            "每頁四重雜湊經系統自動組合為單一 Step Hash，而所有 Step Hash 再依序整合為最終之 Final Event Hash。\n"
            "Final Event Hash 為整份創作過程的唯一驗證憑證，代表該份報告內所有頁面與內容在生成當下的完整性。\n"
            "任何後續對圖像、提示詞或時間資料的竄改，皆將導致對應之 Step Hash 與 Final Event Hash 不一致，可藉此進行真偽比對與法律層面的舉證。"
        )
        self.chapter_body(desc)

        self.chapter_title("最終事件雜湊（Final Event Hash）")
        self.multi_cell(0, 8, proof_data["event_proof"]["final_event_hash"], border=1, align="C")

        qr_data = proof_data["verification"]["verify_url"]
        qr = qrcode.make(qr_data)
        qr_path = os.path.join(app.config["UPLOAD_FOLDER"], f"qr_{proof_data['report_id'][:10]}.png")
        qr.save(qr_path)
        self.image(qr_path, w=50, x=(self.w - 50) / 2)

# === D1. 全域狀態 ===
session_previews = []
latest_proof_data = None

# === D2. 首頁 ===
@app.route('/')
def index():
    """首頁初始化，重置狀態"""
    global session_previews, latest_proof_data
    session_previews = []
    latest_proof_data = None
    return render_template('index.html', api_key_set=bool(API_key))

# === E1. /generate: 生成預覽 ===
@app.route('/generate', methods=['POST'])
def generate():
    if not API_key:
        return jsonify({"error": "BFL_API_KEY 未設定"}), 500

    data = request.json
    prompt = data.get('prompt')
    if not prompt:
        return jsonify({"error": "Prompt 為必填項"}), 400

    try:
        seed = int(data.get('seed', random.randint(1, 10**9)))
        width, height = int(data.get('width', 1024)), int(data.get('height', 1024))

        # E1-1. 呼叫 FLUX API
        endpoint = "https://api.bfl.ai/v1/flux-pro-1.1-ultra"
        headers = {"accept": "application/json", "x-key": API_key, "Content-Type": "application/json"}
        payload = {"prompt": prompt, "width": width, "height": height, "seed": seed}
        res = requests.post(endpoint, headers=headers, json=payload, timeout=60)
        res.raise_for_status()
        polling_url = res.json().get('polling_url')

        # E1-2. 輪詢取得圖像 URL
        start = time.time(); image_url = None
        while time.time() - start < 120:
            poll = requests.get(polling_url, headers={"x-key": API_key}, timeout=30).json()
            if poll.get('status') == 'Ready':
                image_url = poll['result']['sample']; break
            time.sleep(1)

        if not image_url:
            return jsonify({"error": "生成逾時"}), 500

        # E1-3. 儲存預覽圖
        img_bytes = requests.get(image_url).content
        filename = f"preview_v{len(session_previews) + 1}_{int(time.time())}.png"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        Image.open(io.BytesIO(img_bytes)).save(filepath)

        session_previews.append({
            "prompt": prompt,
            "seed": seed,
            "model": "flux-pro-1.1-ultra",
            "filepath": filepath,
            "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()
        })

        # === E1-4. 回傳結果（新增版本號） ===
        return jsonify({
            "success": True,
            "preview_url": url_for('static_preview', filename=filename),
            "version": len(session_previews)  # 新增版本索引供前端顯示
        })

# === E2. /finalize_session: 封存並生成 JSON ===
@app.route('/finalize_session', methods=['POST'])
def finalize_session():
    global latest_proof_data
    applicant = request.json.get('applicant_name')
    if not applicant or not session_previews:
        return jsonify({"error": "資料不足"}), 400

    try:
        snapshots = []
        step_hashes = []

        for i, p in enumerate(session_previews):
            with open(p['filepath'], 'rb') as f:
                img_b64 = base64.b64encode(f.read()).decode('utf-8')

            # 四重雜湊 + Step Hash
            hashes = compute_step_hash(
                ts_iso=p['timestamp_utc'],
                img_b64=img_b64,
                prompt=p['prompt'],
                seed=p['seed']
            )

            snapshot = {
                "version_index": i + 1,
                "timestamp_utc": p['timestamp_utc'],
                "prompt": p['prompt'],
                "seed": p['seed'],
                "model": p['model'],
                "content_base64": img_b64,

                # 新增：四重雜湊與 Step Hash
                "timestamp_hash": hashes["timestamp_hash"],
                "image_hash": hashes["image_hash"],
                "prompt_hash": hashes["prompt_hash"],
                "seed_hash": hashes["seed_hash"],
                "step_hash": hashes["step_hash"]
            }
            snapshots.append(snapshot)
            step_hashes.append(hashes["step_hash"])

        # 最終事件雜湊：按版本順序累積 Step Hash
        final_event_hash = sha256_text(json.dumps({"steps": step_hashes}, sort_keys=True, ensure_ascii=False))

        proof = {
            "report_id": str(uuid.uuid4()),
            "issuer": "WesmartAI Inc.",
            "applicant": applicant,
            "issued_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "event_proof": {
                # 取代 trace_token：不再輸出 trace_token
                "final_event_hash": final_event_hash,
                "snapshots": snapshots
            },
            "verification": {"verify_url": f"https://wesmart.ai/verify?hash={final_event_hash}"}
        }

        path = os.path.join(app.config['UPLOAD_FOLDER'], f"proof_event_{proof['report_id']}.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(proof, f, ensure_ascii=False, indent=2)

        latest_proof_data = proof
        # 同步回傳下載原圖連結（維持原行為）
        image_urls = [url_for('static_download', filename=os.path.basename(p['filepath'])) for p in session_previews]
        return jsonify({"success": True, "image_urls": image_urls})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
# === E3. /create_report: PDF 報告 ===
@app.route('/create_report', methods=['POST'])
def create_report():
    if not latest_proof_data:
        return jsonify({"error": "尚未完成封存"}), 400

    try:
        pdf = WesmartPDFReport()
        pdf.create_cover(latest_proof_data)
        pdf.create_generation_details_page(latest_proof_data)
        pdf.create_conclusion_page(latest_proof_data)
        filename = f"WesmartAI_Report_{latest_proof_data['report_id']}.pdf"
        path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        pdf.output(path)
        return jsonify({"success": True, "report_url": url_for('static_download', filename=filename)})
    except Exception as e:
        return jsonify({"error": str(e)})

# === F. 靜態檔案 ===
@app.route('/static/preview/<path:filename>')
def static_preview(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/static/download/<path:filename>')
def static_download(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

# === G. 啟動服務 ===
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)







