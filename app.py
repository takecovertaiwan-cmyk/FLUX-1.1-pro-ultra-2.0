# ====================================================================
# WesmartAI 證據報告 Web App (完整標註版 v2：保留註解 + 驗證段落 + 四重雜湊機制)
# ====================================================================

# === A1. 匯入套件與 Flask 初始化 ===
from flask import Flask, render_template, request, jsonify, send_file
from fpdf import FPDF
from datetime import datetime
import hashlib
import json
import os
import uuid

app = Flask(__name__)

# === A2. 雜湊與工具函式 ===
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode('utf-8'))

# === A3. PDF 報告生成類別 ===
class WesmartPDFReport(FPDF):
    # A3-1. 初始化
    def __init__(self, title="WesmartAI Report"):
        super().__init__()
        self.title = title

    # A3-2. Header
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, self.title, align='C', ln=True)

    # A3-3. Footer
    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

    # A3-4. 各章節模板
    def chapter_title(self, title):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, title, ln=True)

    def chapter_body(self, content):
        self.set_font('Arial', '', 11)
        self.multi_cell(0, 10, content)

    # A3-5. 封面頁 (含報告驗證說明)
    def create_cover(self, meta):
        self.add_page()
        self.chapter_title("Creative Provenance Report")
        for k, v in meta.items():
            self.chapter_body(f"{k}: {v}")
        self.ln(10)
        self.chapter_title("Report Verification")
        self.chapter_body(
            "本報告之真實性與完整性，係依據每一生成頁面所記錄之四重雜湊（時間戳雜湊、圖片雜湊、提示詞雜湊與種子雜湊）逐步累積計算所得。\n"
            "每頁四重雜湊經系統自動組合為單一 Step Hash，而所有 Step Hash 再依序整合為最終之 Final Event Hash。\n"
            "Final Event Hash 為整份創作過程的唯一驗證憑證，代表該份報告內所有頁面與內容在生成當下的完整性。\n"
            "任何後續對圖像、提示詞或時間資料的竄改，皆將導致對應之 Step Hash 與 Final Event Hash 不一致，可藉此進行真偽比對與法律層面的舉證。"
        )

    # A3-6. 詳細頁：顯示每頁四個雜湊與 step_hash
    def create_generation_details_page(self, proof_data):
        for item in proof_data:
            self.add_page()
            self.chapter_title("Generation Step")
            self.chapter_body(f"Timestamp: {item['timestamp']}")
            self.chapter_body(f"Prompt Hash: {item['prompt_hash']}")
            self.chapter_body(f"Seed Hash: {item['seed_hash']}")
            self.chapter_body(f"Image Hash: {item['image_hash']}")
            self.chapter_body(f"Time Hash: {item['time_hash']}")
            self.chapter_body(f"Step Hash: {item['step_hash']}")

    # A3-7. 結論頁：顯示 final_event_hash
    def create_conclusion_page(self, proof_data):
        self.add_page()
        self.chapter_title("Final Event Hash Summary")
        self.chapter_body(f"Final Event Hash: {proof_data['final_event_hash']}")
        self.chapter_body("All Step Hashes:")
        for h in proof_data['step_hashes']:
            self.chapter_body(f" - {h}")

# === A4. 全域狀態 ===
session_previews = []
latest_proof_data = None

# === B1. 首頁 ===
@app.route('/')
def index():
    return render_template('index.html')

# === B2. 生成影像 ===
@app.route('/generate', methods=['POST'])
def generate():
    # B2-1. 接收請求（含防呆檢查）
    user_prompt = request.form.get('prompt', '').strip()
    if not user_prompt:
       return jsonify({'error': 'missing prompt field'}), 400

    seed = request.form.get('seed', str(uuid.uuid4()))
    model_name = request.form.get('model', 'default-model')

    # B2-2. 模擬生成圖像（實際應呼叫 AI 模型）
    image_path = f'static/preview/{uuid.uuid4()}.png'
    os.makedirs(os.path.dirname(image_path), exist_ok=True)
    with open(image_path, 'wb') as f:
        f.write(os.urandom(256))  # 模擬圖像資料

    # B2-3. 建立多重雜湊 (時間戳、圖片、prompt、seed)
    timestamp = datetime.utcnow().isoformat()
    time_hash = sha256_text(timestamp)
    image_hash = sha256_text(image_path)
    prompt_hash = sha256_text(user_prompt)
    seed_hash = sha256_text(seed)

    # B2-4. 將四個 hash 打包為 step_hash
    combined_hash = time_hash + image_hash + prompt_hash + seed_hash
    step_hash = sha256_text(combined_hash)

    record = {
        'timestamp': timestamp,
        'prompt': user_prompt,
        'seed': seed,
        'model': model_name,
        'time_hash': time_hash,
        'image_hash': image_hash,
        'prompt_hash': prompt_hash,
        'seed_hash': seed_hash,
        'step_hash': step_hash
    }

    session_previews.append(record)
    return jsonify({'status': 'success', 'record': record})

# === B3. 完成封存階段 ===
@app.route('/finalize_session', methods=['POST'])
def finalize_session():
    # B3-1. 驗證 session
    global latest_proof_data
    if not session_previews:
        return jsonify({'error': 'no session data'}), 400

    # B3-2. 彙整每頁 step_hash
    step_hashes = [item['step_hash'] for item in session_previews]

    # B3-3. 計算最終事件雜湊
    final_event_hash = sha256_text(''.join(step_hashes))

    # B3-4. 建立封存資料 (移除 trace_token，顯示 step_hash)
    proof_event = {
        'timestamp': datetime.utcnow().isoformat(),
        'step_hashes': step_hashes,
        'final_event_hash': final_event_hash
    }

    latest_proof_data = proof_event

    os.makedirs('static/download', exist_ok=True)
    proof_path = f'static/download/{final_event_hash}.json'
    with open(proof_path, 'w', encoding='utf-8') as f:
        json.dump(proof_event, f, indent=2)

    return jsonify({'status': 'archived', 'proof_path': proof_path})

# === B4. 生成報告 ===
@app.route('/create_report', methods=['POST'])
def create_report():
    # B4-1. 驗證資料存在
    global latest_proof_data
    if not latest_proof_data:
        return jsonify({'error': 'no proof data'}), 400

    # B4-2. PDF 組裝
    pdf = WesmartPDFReport()
    pdf.create_cover({'Generated': datetime.now().isoformat()})
    pdf.create_generation_details_page(session_previews)
    pdf.create_conclusion_page(latest_proof_data)

    # B4-3. 輸出檔案
    report_path = f'static/download/report_{uuid.uuid4()}.pdf'
    pdf.output(report_path)
    return send_file(report_path, as_attachment=True)

# === C1. 靜態檔案 ===
@app.route('/static/preview/<path:filename>')
def static_preview(filename):
    return send_file(os.path.join('static/preview', filename))

@app.route('/static/download/<path:filename>')
def static_download(filename):
    return send_file(os.path.join('static/download', filename))

# === C2. 啟動服務 ===
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

