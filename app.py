import re
import uuid
import io
import os
import zipfile
import subprocess
import tempfile
from flask import Flask, request, jsonify, send_file, render_template
from pypdf import PdfReader, PdfWriter
from werkzeug.utils import secure_filename

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 MB

# ── Allowed Extensions ──────────────────────────────────────────────────────
PDF_EXT = {'pdf'}
IMAGE_EXT = {'jpg', 'jpeg', 'png', 'bmp', 'tiff', 'gif', 'webp'}
DOC_EXT = {'docx', 'doc', 'pptx', 'ppt'}
ALL_CONVERT_EXT = IMAGE_EXT | DOC_EXT

# ── In-Memory Stores ─────────────────────────────────────────────────────────
# Each dict maps session/file_id → BytesIO or dict of streams
merger_sessions   = {}
split_sessions    = {}
extract_sessions  = {}
result_files      = {}   # file_id → {'buffer': BytesIO, 'filename': str, 'mime': str}


# ── Generic Helpers ───────────────────────────────────────────────────────────
def allowed(filename, exts):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in exts


def get_page_count(stream):
    try:
        stream.seek(0)
        return len(PdfReader(stream).pages)
    except Exception:
        return 0


def parse_page_range(range_str, max_pages):
    """Parse '1-3,5,7-end' into a 0-indexed list of page numbers."""
    pages = []
    range_str = range_str.strip().replace('end', str(max_pages))
    for part in range_str.split(','):
        part = part.strip()
        if '-' in part:
            try:
                s, e = part.split('-', 1)
                for i in range(int(s.strip()), int(e.strip()) + 1):
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


def store_result(buf, filename, mime='application/pdf'):
    fid = uuid.uuid4().hex
    result_files[fid] = {'buffer': buf, 'filename': filename, 'mime': mime}
    return fid


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/merger')
def merger_page():
    return render_template('merger.html')

@app.route('/splitter')
def splitter_page():
    return render_template('splitter.html')

@app.route('/extractor')
def extractor_page():
    return render_template('extractor.html')

@app.route('/converter')
def converter_page():
    return render_template('converter.html')


# ═══════════════════════════════════════════════════════════════════════════════
# PDF MERGER  (two-step: upload → merge)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/merger/upload', methods=['POST'])
def merger_upload():
    if 'pdf1' not in request.files or 'pdf2' not in request.files:
        return jsonify({'error': 'Please upload both PDF files.'}), 400

    pdf1, pdf2 = request.files['pdf1'], request.files['pdf2']

    if pdf1.filename == '' or pdf2.filename == '':
        return jsonify({'error': 'Both files must be selected.'}), 400

    if not allowed(pdf1.filename, PDF_EXT) or not allowed(pdf2.filename, PDF_EXT):
        return jsonify({'error': 'Only PDF files are allowed.'}), 400

    s1 = io.BytesIO(pdf1.read())
    s2 = io.BytesIO(pdf2.read())
    pages1 = get_page_count(s1)
    pages2 = get_page_count(s2)

    if pages1 == 0 or pages2 == 0:
        return jsonify({'error': 'One or both PDFs are corrupt or empty.'}), 400

    sid = uuid.uuid4().hex[:8]
    merger_sessions[sid] = {'pdf1': s1, 'pdf2': s2}

    return jsonify({
        'session_id': sid,
        'pdf1': {'name': secure_filename(pdf1.filename), 'pages': pages1},
        'pdf2': {'name': secure_filename(pdf2.filename), 'pages': pages2},
    })


@app.route('/merger/merge', methods=['POST'])
def merger_merge():
    data = request.get_json() or {}
    sid = data.get('session_id')
    command = data.get('command', 'pdf1 pdf2').strip().lower()

    if not sid or sid not in merger_sessions:
        return jsonify({'error': 'Session not found or expired.'}), 404

    streams = merger_sessions[sid]
    fid, pages, error = _do_merge(streams['pdf1'], streams['pdf2'], command)

    if error:
        return jsonify({'error': error}), 400

    return jsonify({'success': True, 'pages': pages, 'download_url': f'/download/{fid}'})


def _do_merge(s1, s2, command):
    try:
        s1.seek(0); s2.seek(0)
        r1, r2 = PdfReader(s1), PdfReader(s2)
        pg1, pg2 = list(r1.pages), list(r2.pages)
        c1, c2 = len(pg1), len(pg2)
        writer = PdfWriter()

        if 'pdf1:' in command or 'pdf2:' in command:
            for pdf_num, rng in re.compile(r'pdf(\d)\s*:\s*([\d,\-end]+)').findall(command):
                src = pg1 if pdf_num == '1' else pg2
                cnt = c1 if pdf_num == '1' else c2
                for idx in parse_page_range(rng, cnt):
                    writer.add_page(src[idx])

        elif any(k in command for k in ('interleave', 'alternate', 'alternating')):
            for i in range(max(c1, c2)):
                if i < c1: writer.add_page(pg1[i])
                if i < c2: writer.add_page(pg2[i])

        elif 'odd' in command and 'even' in command:
            if command.index('odd') < command.index('even'):
                for i, p in enumerate(pg1):
                    if (i + 1) % 2 == 1: writer.add_page(p)
                for i, p in enumerate(pg2):
                    if (i + 1) % 2 == 0: writer.add_page(p)
            else:
                for i, p in enumerate(pg1):
                    if (i + 1) % 2 == 0: writer.add_page(p)
                for i, p in enumerate(pg2):
                    if (i + 1) % 2 == 1: writer.add_page(p)

        elif 'reverse' in command:
            for p in reversed(pg1 + pg2): writer.add_page(p)

        elif command.startswith('pdf2') or 'pdf2 then pdf1' in command or 'pdf2 first' in command:
            for p in pg2: writer.add_page(p)
            for p in pg1: writer.add_page(p)

        elif command in ('pdf1', 'only pdf1', 'pdf1 only'):
            for p in pg1: writer.add_page(p)

        elif command in ('pdf2', 'only pdf2', 'pdf2 only'):
            for p in pg2: writer.add_page(p)

        else:
            for p in pg1: writer.add_page(p)
            for p in pg2: writer.add_page(p)

        if not writer.pages:
            return None, None, "No pages were added to the output."

        buf = io.BytesIO()
        writer.write(buf)
        buf.seek(0)
        return store_result(buf, 'merged_output.pdf'), len(writer.pages), None

    except Exception as e:
        return None, None, str(e)


# ═══════════════════════════════════════════════════════════════════════════════
# PDF SPLITTER
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/splitter/upload', methods=['POST'])
def splitter_upload():
    if 'pdf' not in request.files:
        return jsonify({'error': 'No file uploaded.'}), 400
    f = request.files['pdf']
    if not f.filename or not allowed(f.filename, PDF_EXT):
        return jsonify({'error': 'Only PDF files are allowed.'}), 400

    stream = io.BytesIO(f.read())
    pages = get_page_count(stream)
    if pages == 0:
        return jsonify({'error': 'PDF is corrupt or empty.'}), 400

    sid = uuid.uuid4().hex[:8]
    split_sessions[sid] = {'stream': stream, 'pages': pages}

    return jsonify({'session_id': sid, 'name': secure_filename(f.filename), 'pages': pages})


def parse_split_command(command, max_pages):
    """
    Returns list of (part_name, [0-indexed pages]) or None on error.
    Supported:
      individual / each  → one PDF per page
      every N            → groups of N pages
      odd / even         → filter pages
      1-3, 4-6, 7-end   → named segments (comma-separated ranges → multiple PDFs)
      1-5                → single range (one PDF)
    """
    cmd = command.strip().lower()

    if cmd in ('individual', 'each', 'pages', 'all pages', 'split all', 'one per page'):
        return [(f'page_{i + 1:04d}', [i]) for i in range(max_pages)]

    m = re.match(r'every\s+(\d+)', cmd)
    if m:
        n = max(1, int(m.group(1)))
        parts = []
        for i in range(0, max_pages, n):
            grp = list(range(i, min(i + n, max_pages)))
            parts.append((f'pages_{grp[0]+1}-{grp[-1]+1}', grp))
        return parts

    if cmd in ('odd', 'odd pages'):
        return [('odd_pages', [i for i in range(max_pages) if (i + 1) % 2 == 1])]

    if cmd in ('even', 'even pages'):
        return [('even_pages', [i for i in range(max_pages) if (i + 1) % 2 == 0])]

    # Comma-separated ranges → multiple parts
    raw_parts = [p.strip() for p in cmd.split(',')]
    all_range_like = all(re.match(r'^\d+(\s*-\s*(\d+|end))?$', p) for p in raw_parts)

    if all_range_like and len(raw_parts) > 1:
        result = []
        for rp in raw_parts:
            idxs = parse_page_range(rp, max_pages)
            if idxs:
                label = rp.strip().replace(' ', '').replace('-', 'to')
                result.append((f'pages_{label}', idxs))
        return result if result else None

    # Single range → one PDF
    idxs = parse_page_range(cmd, max_pages)
    if idxs:
        return [('split_output', idxs)]

    return None


@app.route('/splitter/split', methods=['POST'])
def splitter_split():
    data = request.get_json() or {}
    sid = data.get('session_id')
    command = data.get('command', 'individual').strip()

    if not sid or sid not in split_sessions:
        return jsonify({'error': 'Session not found or expired.'}), 404

    info = split_sessions[sid]
    stream = info['stream']
    max_pages = info['pages']

    plan = parse_split_command(command, max_pages)
    if plan is None:
        return jsonify({'error': 'Could not parse split command. Check the syntax reference below.'}), 400

    stream.seek(0)
    reader = PdfReader(stream)
    all_pages = list(reader.pages)

    parts = []
    for name, idxs in plan:
        w = PdfWriter()
        for idx in idxs:
            if 0 <= idx < max_pages:
                w.add_page(all_pages[idx])
        if w.pages:
            buf = io.BytesIO()
            w.write(buf)
            buf.seek(0)
            parts.append((name, buf))

    if not parts:
        return jsonify({'error': 'No pages matched. Nothing to output.'}), 400

    if len(parts) == 1:
        fid = store_result(parts[0][1], f'{parts[0][0]}.pdf')
        return jsonify({
            'success': True, 'count': 1,
            'total_parts': 1,
            'download_url': f'/download/{fid}',
            'filename': f'{parts[0][0]}.pdf',
        })
    else:
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for name, buf in parts:
                buf.seek(0)
                zf.writestr(f'{name}.pdf', buf.read())
        zip_buf.seek(0)
        fid = store_result(zip_buf, 'split_parts.zip', 'application/zip')
        return jsonify({
            'success': True,
            'total_parts': len(parts),
            'download_url': f'/download/{fid}',
            'filename': 'split_parts.zip',
        })


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE EXTRACTOR
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/extractor/upload', methods=['POST'])
def extractor_upload():
    if 'pdf' not in request.files:
        return jsonify({'error': 'No file uploaded.'}), 400
    f = request.files['pdf']
    if not f.filename or not allowed(f.filename, PDF_EXT):
        return jsonify({'error': 'Only PDF files are allowed.'}), 400

    stream = io.BytesIO(f.read())
    pages = get_page_count(stream)
    if pages == 0:
        return jsonify({'error': 'PDF is corrupt or empty.'}), 400

    sid = uuid.uuid4().hex[:8]
    extract_sessions[sid] = {'stream': stream, 'pages': pages}

    return jsonify({'session_id': sid, 'name': secure_filename(f.filename), 'pages': pages})


@app.route('/extractor/extract', methods=['POST'])
def extractor_extract():
    data = request.get_json() or {}
    sid = data.get('session_id')
    range_str = data.get('range', '').strip()

    if not sid or sid not in extract_sessions:
        return jsonify({'error': 'Session not found or expired.'}), 404
    if not range_str:
        return jsonify({'error': 'Page range is required.'}), 400

    info = extract_sessions[sid]
    stream = info['stream']
    max_pages = info['pages']

    page_indices = parse_page_range(range_str, max_pages)
    if not page_indices:
        return jsonify({'error': f'No valid pages found in "{range_str}". Pages must be between 1 and {max_pages}.'}), 400

    stream.seek(0)
    reader = PdfReader(stream)
    all_pages = list(reader.pages)
    writer = PdfWriter()

    for idx in page_indices:
        if 0 <= idx < max_pages:
            writer.add_page(all_pages[idx])

    if not writer.pages:
        return jsonify({'error': 'No pages were extracted.'}), 400

    buf = io.BytesIO()
    writer.write(buf)
    buf.seek(0)
    fid = store_result(buf, 'extracted_pages.pdf')

    return jsonify({
        'success': True,
        'extracted': len(writer.pages),
        'total': max_pages,
        'download_url': f'/download/{fid}',
    })


# ═══════════════════════════════════════════════════════════════════════════════
# FILE CONVERTER
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/converter/convert', methods=['POST'])
def converter_convert():
    if 'files' not in request.files:
        return jsonify({'error': 'No files uploaded.'}), 400

    files = request.files.getlist('files')
    if not files or all(f.filename == '' for f in files):
        return jsonify({'error': 'No files selected.'}), 400

    # Separate images from documents
    image_files, doc_files = [], []
    for f in files:
        ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
        if ext in IMAGE_EXT:
            image_files.append(f)
        elif ext in DOC_EXT:
            doc_files.append(f)
        else:
            return jsonify({'error': f'Unsupported file type: .{ext}'}), 400

    # Cannot mix images and docs in one batch
    if image_files and doc_files:
        return jsonify({'error': 'Please convert images and documents separately.'}), 400

    if image_files:
        return _convert_images(image_files)
    else:
        return _convert_doc(doc_files[0])


def _convert_images(files):
    if not PIL_AVAILABLE:
        return jsonify({'error': 'Pillow is not installed. Run: pip install Pillow'}), 500

    images = []
    for f in files:
        try:
            data = f.read()
            img = Image.open(io.BytesIO(data))
            if img.mode not in ('RGB',):
                img = img.convert('RGB')
            images.append(img)
        except Exception as e:
            return jsonify({'error': f'Could not open "{f.filename}": {e}'}), 400

    if not images:
        return jsonify({'error': 'No valid images.'}), 400

    buf = io.BytesIO()
    images[0].save(buf, format='PDF', save_all=True, append_images=images[1:], resolution=150)
    buf.seek(0)
    fid = store_result(buf, 'converted.pdf')
    return jsonify({'success': True, 'download_url': f'/download/{fid}', 'filename': 'converted.pdf'})


def _convert_doc(f):
    fname = secure_filename(f.filename)
    with tempfile.TemporaryDirectory() as tmpdir:
        in_path = os.path.join(tmpdir, fname)
        f.seek(0)
        with open(in_path, 'wb') as out:
            out.write(f.read())

        try:
            result = subprocess.run(
                ['libreoffice', '--headless', '--convert-to', 'pdf', '--outdir', tmpdir, in_path],
                capture_output=True, timeout=60, text=True
            )
        except FileNotFoundError:
            return jsonify({'error': (
                'LibreOffice is not installed on this server. '
                'Install it with: sudo apt install libreoffice  '
                '(or download from libreoffice.org)'
            )}), 500
        except subprocess.TimeoutExpired:
            return jsonify({'error': 'Conversion timed out. The file may be too large or complex.'}), 500

        if result.returncode != 0:
            return jsonify({'error': f'LibreOffice error: {result.stderr or result.stdout}'}), 500

        # Locate output PDF
        base = os.path.splitext(fname)[0]
        out_path = os.path.join(tmpdir, base + '.pdf')
        if not os.path.exists(out_path):
            pdfs = [x for x in os.listdir(tmpdir) if x.endswith('.pdf')]
            if not pdfs:
                return jsonify({'error': 'Conversion produced no output file.'}), 500
            out_path = os.path.join(tmpdir, pdfs[0])

        with open(out_path, 'rb') as pdf_f:
            buf = io.BytesIO(pdf_f.read())
        fid = store_result(buf, base + '.pdf')
        return jsonify({'success': True, 'download_url': f'/download/{fid}', 'filename': base + '.pdf'})


# ═══════════════════════════════════════════════════════════════════════════════
# UNIVERSAL DOWNLOAD
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/download/<file_id>')
def download(file_id):
    if file_id not in result_files:
        return jsonify({'error': 'File not found or expired.'}), 404
    info = result_files[file_id]
    info['buffer'].seek(0)
    return send_file(
        info['buffer'],
        as_attachment=True,
        download_name=info['filename'],
        mimetype=info['mime'],
    )


# ── Legacy route (keep backward compat) ──────────────────────────────────────
@app.route('/upload', methods=['POST'])
def legacy_upload():
    return merger_upload()

@app.route('/merge', methods=['POST'])
def legacy_merge():
    return merger_merge()


if __name__ == '__main__':
    print("PDF Tools Suite running at http://localhost:5000")
    app.run(debug=True, port=5000)