# 📄 PDF Merger — Smart Document Tool
### 2nd Year College Project | Built with Python Flask + pypdf

---

## 🚀 What This Project Does

A web application that lets you **upload two PDF files** and merge them
in any order or combination using **simple text commands**.

### Supported Merge Commands

| Command | What it does |
|---------|-------------|
| `pdf1 pdf2` | All PDF1 pages, then all PDF2 pages (default) |
| `pdf2 pdf1` | PDF2 first, then PDF1 |
| `interleave` | Alternate pages: P1-pg1, P2-pg1, P1-pg2 … |
| `reverse` | Merge both, then reverse all page order |
| `pdf1:1-3, pdf2:2-4` | Custom page ranges (1-indexed, use 'end' for last page) |
| `odd from pdf1, even from pdf2` | Odd pages from PDF1, even from PDF2 |
| `only pdf1` | Output only PDF1 pages |
| `only pdf2` | Output only PDF2 pages |

---

## 🛠️ Tech Stack

- **Backend**: Python 3.10+, Flask, pypdf
- **Frontend**: Vanilla HTML/CSS/JavaScript (no frameworks needed)
- **Styling**: Custom dark theme, Google Fonts

---

## ⚙️ Setup Instructions

### 1. Prerequisites
Make sure you have **Python 3.10+** installed.
Check with: `python --version`

### 2. Clone / Download the project
```
pdf_merger/
├── app.py                  ← Flask backend (main logic)
├── requirements.txt        ← Python dependencies
├── README.md               ← This file
├── static/
│   ├── uploads/            ← Temp folder for uploaded PDFs
│   └── outputs/            ← Merged PDFs saved here
└── templates/
    └── index.html          ← Frontend UI
```

### 3. Install Dependencies
Open a terminal in the project folder and run:
```bash
pip install -r requirements.txt
```

### 4. Run the App
```bash
python app.py
```

Then open your browser and go to:
```
http://localhost:5000
```

---

## 🎯 How to Use

1. **Upload** — Drag and drop (or click to browse) two PDF files into the upload boxes.
2. **Analyse** — Click "Analyse Both PDFs" to upload them to the server.
3. **Command** — Type a merge command or click one of the quick preset buttons.
4. **Merge** — Click "MERGE DOCUMENTS" (or press Ctrl+Enter).
5. **Download** — Click the green Download button to save your merged PDF.

---

## 📁 Project Structure Explained

### `app.py`
The Flask backend. Contains:
- `/` — Serves the main HTML page
- `/upload` — Accepts two PDFs, saves them, returns page counts
- `/merge` — Accepts a merge command, runs the merge logic, saves output
- `/download/<filename>` — Serves the merged PDF for download
- `/cleanup` — Deletes temp files after download

### `parse_page_range(range_str, max_pages)`
Parses strings like `"1-3"`, `"2,4,6"`, `"2-end"` into page index lists.

### `merge_pdfs(pdf1_path, pdf2_path, command)`
Core merge function. Uses a series of `if/elif` checks to detect which
merge strategy the user wants and builds the output PDF accordingly.

### `templates/index.html`
Single-page UI with:
- Drag-and-drop file upload zones
- Command textarea with preset buttons
- Status messages and result card
- Download link

---

## 💡 Possible Extensions (for viva / extras)

- [ ] Support merging more than 2 PDFs
- [ ] Add a page preview (thumbnail) before merging
- [ ] Support password-protected PDFs
- [ ] Add page reordering via drag-and-drop UI
- [ ] Generate a merge history / log
- [ ] Deploy to cloud (Render, Railway, PythonAnywhere — all free tiers)

---

## 🐛 Common Issues

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError: flask` | Run `pip install -r requirements.txt` |
| Port 5000 already in use | Change `port=5000` to `port=5001` in app.py |
| File upload fails | Check that `static/uploads/` folder exists |
| Empty output PDF | Check your page range — ensure page numbers exist in the PDF |

---

*Built with ❤️ using Python Flask and pypdf*