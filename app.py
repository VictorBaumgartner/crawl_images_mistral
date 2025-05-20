import logging
import os
import uuid
import datetime
from flask import Flask, request, render_template, redirect, url_for, flash
from werkzeug.utils import secure_filename
from pathlib import Path
import threading # For running background tasks
from concurrent.futures import ThreadPoolExecutor # More robust threading

# Import the core crawler logic
from crawler import run_crawler_job_sync # Renamed and wrapped for sync execution

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'a_super_secret_key_for_dev') # Change this in production
app.config['UPLOAD_FOLDER'] = Path('./uploads') # Where CSVs are temporarily stored
app.config['JOBS_FOLDER'] = Path('./jobs') # Where all job outputs (images, analysis) go

# Create necessary directories on startup
app.config['UPLOAD_FOLDER'].mkdir(parents=True, exist_ok=True)
app.config['JOBS_FOLDER'].mkdir(parents=True, exist_ok=True)

# Configure Flask logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s [Flask]')
app.logger.setLevel(logging.INFO)

# Initialize a thread pool for background tasks
executor = ThreadPoolExecutor(max_workers=2) # Limit concurrent jobs if needed

ALLOWED_EXTENSIONS = {'csv'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('upload.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        flash('No file part')
        return redirect(request.url)
    
    file = request.files['file']
    
    if file.filename == '':
        flash('No selected file')
        return redirect(request.url)
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        
        # Create a unique job ID and directory for this run
        job_id = f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}"
        job_output_dir = app.config['JOBS_FOLDER'] / job_id
        job_output_dir.mkdir(parents=True, exist_ok=True)

        # Save the uploaded CSV temporarily within the job directory
        csv_save_path = job_output_dir / "input_urls.csv"
        file.save(csv_save_path)
        
        flash(f'File "{filename}" uploaded. Starting image crawling job (ID: {job_id}).')
        app.logger.info(f"Job {job_id}: CSV saved to {csv_save_path}")

        # Submit the crawling task to the thread pool
        # This function will run in a separate thread, not blocking Flask
        executor.submit(run_crawler_job_sync, csv_save_path, job_output_dir)
        
        # You can add a link here to a status page if you implement one
        return redirect(url_for('index'))
    else:
        flash('Allowed file types are CSV')
        return redirect(request.url)

if __name__ == '__main__':
    # Ensure Playwright drivers are installed
    # This command should be run in your terminal once:
    # playwright install --with-deps
    app.run(debug=True) # Set debug=False for production