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
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)

@app.errorhandler(413)
def too_large(e):
    return jsonify({'success': False, 'message': 'File too large. Maximum 10MB per file.'}), 413

# Security settings
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max per file
app.config['MAX_FILES_PER_UPLOAD'] = 30              # Max 30 files per submission
app.config['MAX_TOTAL_UPLOAD_SIZE'] = 100 * 1024 * 1024  # 100MB total per participant
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['DATA_FOLDER'] = os.path.join(os.path.dirname(__file__), 'data')

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["100 per day", "10 per minute"]
)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['DATA_FOLDER'], exist_ok=True)

# Only allow PDFs and images
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}
ALLOWED_MIMETYPES = {
    'application/pdf',
    'image/png',
    'image/jpeg'
}

DB_PATH = os.path.join(app.config['DATA_FOLDER'], 'participants.json')

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_file(file):
    """Check file extension, mimetype, and magic bytes"""
    if not file or not file.filename:
        return False, "No file provided"
    
    # Check extension
    if not allowed_file(file.filename):
        return False, f"File type not allowed: {file.filename}"
    
    # Check mimetype
    if file.mimetype not in ALLOWED_MIMETYPES:
        return False, f"Invalid file type: {file.mimetype}"
    
    # Check magic bytes (file signature)
    header = file.read(8)
    file.seek(0)  # Reset file pointer
    
    # PDF: %PDF
    # PNG: 89 50 4E 47
    # JPEG: FF D8 FF
    is_pdf = header[:4] == b'%PDF'
    is_png = header[:4] == b'\x89PNG'
    is_jpeg = header[:2] == b'\xff\xd8'
    
    if not (is_pdf or is_png or is_jpeg):
        return False, f"File content doesn't match expected type: {file.filename}"
    
    return True, "OK"

def get_participant_upload_size(participant_id):
    """Calculate total size of files already uploaded by participant"""
    participant_folder = os.path.join(app.config['UPLOAD_FOLDER'], participant_id)
    if not os.path.exists(participant_folder):
        return 0
    total = 0
    for f in os.listdir(participant_folder):
        total += os.path.getsize(os.path.join(participant_folder, f))
    return total

def is_duplicate_file(filepath, participant_folder):
    """Check if file with same hash already exists"""
    if not os.path.exists(participant_folder):
        return False
    
    new_hash = hashlib.md5(open(filepath, 'rb').read()).hexdigest()
    
    for existing_file in os.listdir(participant_folder):
        existing_path = os.path.join(participant_folder, existing_file)
        if os.path.isfile(existing_path):
            existing_hash = hashlib.md5(open(existing_path, 'rb').read()).hexdigest()
            if new_hash == existing_hash:
                return True
    return False

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
        email = request.form.get('email', '').strip().lower()
        participant_id = request.form.get('participantId', str(uuid.uuid4()))
        
        # Validate email
        if not email or '@' not in email or '.' not in email:
            return jsonify({'success': False, 'message': 'Valid email required'}), 400
        
        # Check number of files
        files = request.files.getlist('bills')
        if len(files) > app.config['MAX_FILES_PER_UPLOAD']:
            return jsonify({'success': False, 'message': f'Maximum {app.config["MAX_FILES_PER_UPLOAD"]} files allowed'}), 400
        
        if len(files) == 0:
            return jsonify({'success': False, 'message': 'No files provided'}), 400
        
        # Check total upload size for this participant
        existing_size = get_participant_upload_size(participant_id)
        new_size = sum(f.seek(0, 2) or f.tell() for f in files)
        for f in files:
            f.seek(0)  # Reset file pointers
        
        if existing_size + new_size > app.config['MAX_TOTAL_UPLOAD_SIZE']:
            return jsonify({'success': False, 'message': 'Total upload limit exceeded (100MB max)'}), 400
        
        # Validate each file
        for file in files:
            valid, message = validate_file(file)
            if not valid:
                return jsonify({'success': False, 'message': message}), 400
        
        # Create participant folder
        participant_folder = os.path.join(app.config['UPLOAD_FOLDER'], participant_id)
        os.makedirs(participant_folder, exist_ok=True)
        
        # Save files
        saved_files = []
        skipped_duplicates = 0
        
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                new_filename = f"{timestamp}_{filename}"
                filepath = os.path.join(participant_folder, new_filename)
        
                # Read file content for duplicate check BEFORE saving
                file_content = file.read()
                file_hash = hashlib.md5(file_content).hexdigest()
        
                # Check for duplicates against existing files
                is_duplicate = False
                for existing_file in os.listdir(participant_folder):
                    existing_path = os.path.join(participant_folder, existing_file)
                    if os.path.isfile(existing_path):
                        existing_hash = hashlib.md5(open(existing_path, 'rb').read()).hexdigest()
                        if file_hash == existing_hash:
                            is_duplicate = True
                            skipped_duplicates += 1
                            break
        
                if is_duplicate:
                    continue
        
                # Save the file
                with open(filepath, 'wb') as f:
                    f.write(file_content)
        
                saved_files.append({
                    'original': filename,
                    'saved': new_filename,
                    'size': os.path.getsize(filepath)
                })

        """
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                new_filename = f"{timestamp}_{filename}"
                filepath = os.path.join(participant_folder, new_filename)
                file.save(filepath)
                
                # Check for duplicates
                if is_duplicate_file(filepath, participant_folder):
                    os.remove(filepath)
                    skipped_duplicates += 1
                    continue
                
                saved_files.append({
                    'original': filename,
                    'saved': new_filename,
                    'size': os.path.getsize(filepath)
                })
        """

        if len(saved_files) == 0:
            return jsonify({'success': False, 'message': 'No valid files uploaded'}), 400
        
        # Save to database
        db = read_db()
        db['participants'].append({
            'id': participant_id,
            'email': email,
            'submitted_at': datetime.now().isoformat(),
            'files_count': len(saved_files),
            'files': saved_files,
            'type': 'self-upload',
            'ip': request.remote_addr
        })
        write_db(db)
        
        return jsonify({
            'success': True, 
            'filesCount': len(saved_files),
            'skippedDuplicates': skipped_duplicates
        })
        
    except Exception as e:
        app.logger.error(f"Upload error: {str(e)}")
        return jsonify({'success': False, 'message': 'Upload failed. Please try again.'}), 500

@app.route('/api/request-help', methods=['POST'])
def request_help():
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        
        if not email or '@' not in email or '.' not in email:
            return jsonify({'success': False, 'message': 'Valid email required'}), 400
        
        db = read_db()
        db['participants'].append({
            'id': str(uuid.uuid4()),
            'email': email,
            'submitted_at': datetime.now().isoformat(),
            'files_count': 0,
            'files': [],
            'type': 'assistance-requested',
            'ip': request.remote_addr
        })
        write_db(db)
        
        return jsonify({'success': True})
        
    except Exception as e:
        app.logger.error(f"Help request error: {str(e)}")
        return jsonify({'success': False, 'message': 'Request failed. Please try again.'}), 500

if __name__ == '__main__':
    print("\n" + "="*50)
    print("NJ Energy Study")
    print("="*50)
    print("Running at: http://localhost:5000")
    print("="*50 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=False)
