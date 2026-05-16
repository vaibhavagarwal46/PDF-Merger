import re
import uuid
import io
from flask import Flask, request, jsonify, send_file, render_template
from pypdf import PdfReader, PdfWriter
from werkzeug.utils import secure_filename

app = Flask(__name__)

app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

ALLOWED_EXTENSIONS = {'pdf'}
uploaded_files = {}
merged_files = {}
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_page_count(file_stream):
    try:
        file_stream.seek(0)
        reader = PdfReader(file_stream)
        return len(reader.pages)
    except Exception:
        return 0


def parse_page_range(range_str, max_pages):
    pages = []

    range_str = range_str.strip().replace('end', str(max_pages))

    parts = range_str.split(',')

    for part in parts:
        part = part.strip()

        if '-' in part:
            start, end = part.split('-', 1)

            try:
                s = int(start.strip())
                e = int(end.strip())

                for i in range(s, e + 1):
                    if 1 <= i <= max_pages:
                        pages.append(i - 1)

            except ValueError:
                pass

        else:
            try:
                n = int(part)

                if 1 <= n <= max_pages:
                    pages.append(n - 1)

            except ValueError:
                pass

    return pages


def merge_pdfs(pdf1_stream, pdf2_stream, command):
    try:
        pdf1_stream.seek(0)
        pdf2_stream.seek(0)
        
        reader1 = PdfReader(pdf1_stream)
        reader2 = PdfReader(pdf2_stream)

        writer = PdfWriter()

        pages1 = list(reader1.pages)
        pages2 = list(reader2.pages)

        count1 = len(pages1)
        count2 = len(pages2)

        command = command.strip().lower()

        if 'pdf1:' in command or 'pdf2:' in command:

            segment_pattern = re.compile(r'pdf(\d)\s*:\s*([\d,\-end]+)')
            segments = segment_pattern.findall(command)

            if not segments:
                return None, None, "Invalid page range format."

            for pdf_num, range_str in segments:

                if pdf_num == '1':
                    idxs = parse_page_range(range_str, count1)

                    for idx in idxs:
                        writer.add_page(pages1[idx])

                elif pdf_num == '2':
                    idxs = parse_page_range(range_str, count2)

                    for idx in idxs:
                        writer.add_page(pages2[idx])

        elif 'interleave' in command or 'alternate' in command or 'alternating' in command:

            max_len = max(count1, count2)

            for i in range(max_len):

                if i < count1:
                    writer.add_page(pages1[i])

                if i < count2:
                    writer.add_page(pages2[i])

        elif 'odd' in command and 'even' in command:

            if command.index('odd') < command.index('even'):

                for i, page in enumerate(pages1):
                    if (i + 1) % 2 == 1:
                        writer.add_page(page)

                for i, page in enumerate(pages2):
                    if (i + 1) % 2 == 0:
                        writer.add_page(page)

            else:

                for i, page in enumerate(pages1):
                    if (i + 1) % 2 == 0:
                        writer.add_page(page)

                for i, page in enumerate(pages2):
                    if (i + 1) % 2 == 1:
                        writer.add_page(page)

        elif 'reverse' in command:

            all_pages = pages1 + pages2

            for page in reversed(all_pages):
                writer.add_page(page)

        elif command.startswith('pdf2') or 'pdf2 then pdf1' in command or 'pdf2 first' in command:

            for page in pages2:
                writer.add_page(page)

            for page in pages1:
                writer.add_page(page)

        elif command in ('pdf1', 'only pdf1', 'pdf1 only'):

            for page in pages1:
                writer.add_page(page)

        elif command in ('pdf2', 'only pdf2', 'pdf2 only'):

            for page in pages2:
                writer.add_page(page)

        else:

            for page in pages1:
                writer.add_page(page)

            for page in pages2:
                writer.add_page(page)

        if len(writer.pages) == 0:
            return None, None, "No pages were added."

        pdf_buffer = io.BytesIO()

        writer.write(pdf_buffer)

        pdf_buffer.seek(0)

        file_id = uuid.uuid4().hex

        merged_files[file_id] = pdf_buffer

        return file_id, len(writer.pages), None

    except Exception as e:
        return None, None, str(e)


@app.route('/')
def index():
    return render_template('index.html')
@app.route('/upload', methods=['POST'])
def upload_pdfs():

    if 'pdf1' not in request.files or 'pdf2' not in request.files:
        return jsonify({'error': 'Please upload both PDF files.'}), 400

    pdf1 = request.files['pdf1']
    pdf2 = request.files['pdf2']

    if pdf1.filename == '' or pdf2.filename == '':
        return jsonify({'error': 'Both files must be selected.'}), 400

    if not allowed_file(pdf1.filename) or not allowed_file(pdf2.filename):
        return jsonify({'error': 'Only PDF files are allowed.'}), 400

    session_id = uuid.uuid4().hex[:8]
    pdf1_stream = io.BytesIO(pdf1.read())
    pdf2_stream = io.BytesIO(pdf2.read())

    pages1 = get_page_count(pdf1_stream)
    pages2 = get_page_count(pdf2_stream)

    if pages1 == 0 or pages2 == 0:
        return jsonify({
            'error': 'One or both PDFs are corrupt or empty.'
        }), 400
    uploaded_files[session_id] = {
        'pdf1': pdf1_stream,
        'pdf2': pdf2_stream
    }

    return jsonify({
        'session_id': session_id,
        'pdf1': {
            'name': secure_filename(pdf1.filename),
            'pages': pages1
        },
        'pdf2': {
            'name': secure_filename(pdf2.filename),
            'pages': pages2
        }
    })


@app.route('/merge', methods=['POST'])
def merge():

    data = request.get_json()

    if not data:
        return jsonify({'error': 'No data received.'}), 400

    session_id = data.get('session_id')
    command = data.get('command', 'pdf1 pdf2')

    if not session_id:
        return jsonify({
            'error': 'Session ID missing.'
        }), 400
    if session_id not in uploaded_files:
        return jsonify({
            'error': 'Uploaded files not found or session expired.'
        }), 404

    pdf_streams = uploaded_files[session_id]
    
    file_id, merged_pages, error = merge_pdfs(
        pdf_streams['pdf1'],
        pdf_streams['pdf2'],
        command
    )

    if error:
        return jsonify({'error': error}), 400

    return jsonify({
        'success': True,
        'pages': merged_pages,
        'download_url': f'/download/{file_id}'
    })


@app.route('/download/<file_id>')
def download(file_id):

    if file_id not in merged_files:
        return jsonify({'error': 'File not found.'}), 404

    pdf_buffer = merged_files[file_id]
    pdf_buffer.seek(0)

    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name='merged_output.pdf',
        mimetype='application/pdf'
    )


if __name__ == '__main__':
    print("PDF Merger running at http://localhost:5000")
    app.run(debug=True, port=5000)