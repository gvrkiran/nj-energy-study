"""
NJ Energy Study - Flask Application
Run: python app.py
"""

import os
import json
import uuid
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['DATA_FOLDER'] = os.path.join(os.path.dirname(__file__), 'data')

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['DATA_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp'}
DB_PATH = os.path.join(app.config['DATA_FOLDER'], 'participants.json')

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["100 per day", "10 per minute"]
)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def read_db():
    if not os.path.exists(DB_PATH):
        return {'participants': []}
    with open(DB_PATH, 'r') as f:
        return json.load(f)

def write_db(data):
    with open(DB_PATH, 'w') as f:
        json.dump(data, f, indent=2)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/submit', methods=['POST'])
def submit():
    try:
        email = request.form.get('email')
        participant_id = request.form.get('participantId', str(uuid.uuid4()))
        
        if not email:
            return jsonify({'success': False, 'message': 'Email required'}), 400
        
        participant_folder = os.path.join(app.config['UPLOAD_FOLDER'], participant_id)
        os.makedirs(participant_folder, exist_ok=True)
        
        files = request.files.getlist('bills')
        saved_files = []
        
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                new_filename = f"{timestamp}_{filename}"
                filepath = os.path.join(participant_folder, new_filename)
                file.save(filepath)
                saved_files.append({
                    'original': filename,
                    'saved': new_filename,
                    'size': os.path.getsize(filepath)
                })
        
        db = read_db()
        db['participants'].append({
            'id': participant_id,
            'email': email,
            'submitted_at': datetime.now().isoformat(),
            'files_count': len(saved_files),
            'files': saved_files,
            'type': 'self-upload'
        })
        write_db(db)
        
        return jsonify({'success': True, 'filesCount': len(saved_files)})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/request-help', methods=['POST'])
def request_help():
    try:
        data = request.get_json()
        email = data.get('email')
        
        if not email:
            return jsonify({'success': False, 'message': 'Email required'}), 400
        
        db = read_db()
        db['participants'].append({
            'id': str(uuid.uuid4()),
            'email': email,
            'submitted_at': datetime.now().isoformat(),
            'files_count': 0,
            'files': [],
            'type': 'assistance-requested'
        })
        write_db(db)
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

if __name__ == '__main__':
    print("\n" + "="*50)
    print("NJ Energy Study")
    print("="*50)
    print("Running at: http://localhost:5000")
    print("="*50 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=False)
