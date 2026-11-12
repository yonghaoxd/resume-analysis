# Resume Match Checker

A local web tool that scores a resume against a job description (0–100), shows where points were gained and lost, and suggests concrete edits you can apply with one click.

## What it does

- Upload a resume (PDF, DOCX or TXT) and paste the job scope.
- Breaks the job description into requirements and checks each one against the resume, quoting the evidence.
- Scores five dimensions: skills, experience, keyword coverage, resume quality, education. The AI makes the judgements; the arithmetic is done in code so scores are stable.
- Suggests edits (current sentence → rewritten sentence). Tick the ones you accept, apply them, then download the result as Word or re-score it.
- Keeps a local history so you can see how the score changes between versions.

## Setup (Windows)

1. Install Python 3.11+.
2. Double-click `run.bat`. On first run it installs dependencies and creates a `.env` file.
3. Paste your [DeepSeek](https://platform.deepseek.com) API key into `.env`, save, and run `run.bat` again.
4. The app opens at http://localhost:8000.

PDFs without a text layer (scanned, or made with "Microsoft Print to PDF") are read with OCR. Installing [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) gives the best results; without it a slower built-in fallback is used.

## Privacy

Your resume and the job description are sent to DeepSeek for analysis. History is stored only on your computer in `data/history.db`. The `.env` file and `data/` folder are excluded from git.

## Tests

```
.venv\Scripts\python tests\test_app.py
```
