"""
NJ Energy Study - Flask Application
Run: python app.py
"""

import os
import json
import uuid
import hashlib
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Security settings
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max per file
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['DATA_FOLDER'] = os.path.join(os.path.dirname(__file__), 'data')

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['DATA_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}
ALLOWED_MIMETYPES = {'application/pdf', 'image/png', 'image/jpeg'}
DB_PATH = os.path.join(app.config['DATA_FOLDER'], 'participants.json')
FOLLOWUP_PATH = os.path.join(app.config['DATA_FOLDER'], 'followup_interest.json')

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_file(file):
    if not file or not file.filename:
        return False, "No file provided"
    if not allowed_file(file.filename):
        return False, f"File type not allowed: {file.filename}"
    if file.mimetype not in ALLOWED_MIMETYPES:
        return False, f"Invalid file type: {file.mimetype}"
    header = file.read(8)
    file.seek(0)
    is_pdf = header[:4] == b'%PDF'
    is_png = header[:4] == b'\x89PNG'
    is_jpeg = header[:2] == b'\xff\xd8'
    if not (is_pdf or is_png or is_jpeg):
        return False, f"File content doesn't match expected type: {file.filename}"
    return True, "OK"

def read_db():
    if not os.path.exists(DB_PATH):
        return {'participants': []}
    with open(DB_PATH, 'r') as f:
        return json.load(f)

def write_db(data):
    with open(DB_PATH, 'w') as f:
        json.dump(data, f, indent=2)

def read_followup():
    if not os.path.exists(FOLLOWUP_PATH):
        return {'interested': []}
    with open(FOLLOWUP_PATH, 'r') as f:
        return json.load(f)

def write_followup(data):
    with open(FOLLOWUP_PATH, 'w') as f:
        json.dump(data, f, indent=2)

@app.errorhandler(413)
def too_large(e):
    return jsonify({'success': False, 'message': 'File too large. Maximum 10MB per file.'}), 413

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/submit', methods=['POST'])
def submit():
    try:
        email = request.form.get('email', '').strip().lower()
        participant_id = request.form.get('participantId', str(uuid.uuid4()))
        survey_data_raw = request.form.get('surveyData', '{}')
        
        try:
            survey_data = json.loads(survey_data_raw)
        except:
            survey_data = {}
        
        if not email or '@' not in email:
            return jsonify({'success': False, 'message': 'Valid email required'}), 400
        
        files = request.files.getlist('bills')
        if len(files) == 0:
            return jsonify({'success': False, 'message': 'No files provided'}), 400
        if len(files) > 30:
            return jsonify({'success': False, 'message': 'Maximum 30 files allowed'}), 400
        
        # Validate each file
        for file in files:
            valid, message = validate_file(file)
            if not valid:
                return jsonify({'success': False, 'message': message}), 400
        
        # Create participant folder
        participant_folder = os.path.join(app.config['UPLOAD_FOLDER'], participant_id)
        os.makedirs(participant_folder, exist_ok=True)
        
        # Get existing file hashes to check for duplicates
        existing_hashes = set()
        if os.path.exists(participant_folder):
            for existing_file in os.listdir(participant_folder):
                existing_path = os.path.join(participant_folder, existing_file)
                if os.path.isfile(existing_path):
                    existing_hashes.add(hashlib.md5(open(existing_path, 'rb').read()).hexdigest())
        
        # Save files
        saved_files = []
        skipped = 0
        
        for file in files:
            if file and allowed_file(file.filename):
                file_content = file.read()
                file_hash = hashlib.md5(file_content).hexdigest()
                
                if file_hash in existing_hashes:
                    skipped += 1
                    continue
                
                existing_hashes.add(file_hash)
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                new_filename = f"{timestamp}_{filename}"
                filepath = os.path.join(participant_folder, new_filename)
                
                with open(filepath, 'wb') as f:
                    f.write(file_content)
                
                saved_files.append({
                    'original': filename,
                    'saved': new_filename,
                    'size': len(file_content)
                })
        
        if len(saved_files) == 0:
            return jsonify({'success': False, 'message': 'No valid new files uploaded'}), 400
        
        db = read_db()
        db['participants'].append({
            'id': participant_id,
            'email': email,
            'submitted_at': datetime.now().isoformat(),
            'files_count': len(saved_files),
            'files': saved_files,
            'survey': survey_data,
            'type': 'self-upload',
            'ip': request.remote_addr
        })
        write_db(db)
        
        return jsonify({'success': True, 'filesCount': len(saved_files), 'skipped': skipped})
        
    except Exception as e:
        app.logger.error(f"Upload error: {str(e)}")
        return jsonify({'success': False, 'message': 'Upload failed. Please try again.'}), 500

@app.route('/api/request-help', methods=['POST'])
def request_help():
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        survey_data = data.get('surveyData', {})
        
        if not email or '@' not in email:
            return jsonify({'success': False, 'message': 'Valid email required'}), 400
        
        db = read_db()
        db['participants'].append({
            'id': str(uuid.uuid4()),
            'email': email,
            'submitted_at': datetime.now().isoformat(),
            'files_count': 0,
            'files': [],
            'survey': survey_data,
            'type': 'assistance-requested',
            'ip': request.remote_addr
        })
        write_db(db)
        
        return jsonify({'success': True})
        
    except Exception as e:
        app.logger.error(f"Help request error: {str(e)}")
        return jsonify({'success': False, 'message': 'Request failed. Please try again.'}), 500

@app.route('/api/followup-interest', methods=['POST'])
def followup_interest():
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        participant_id = data.get('participantId', '')
        
        if not email or '@' not in email:
            return jsonify({'success': False, 'message': 'Valid email required'}), 400
        
        followup = read_followup()
        followup['interested'].append({
            'email': email,
            'participant_id': participant_id,
            'submitted_at': datetime.now().isoformat(),
            'ip': request.remote_addr
        })
        write_followup(followup)
        
        return jsonify({'success': True})
        
    except Exception as e:
        app.logger.error(f"Followup interest error: {str(e)}")
        return jsonify({'success': False, 'message': 'Request failed. Please try again.'}), 500

if __name__ == '__main__':
    print("\n" + "="*50)
    print("NJ Energy Study")
    print("="*50)
    print("Running at: http://localhost:5000")
    print("="*50 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=False)
