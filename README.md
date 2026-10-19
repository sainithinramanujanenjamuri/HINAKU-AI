# HINAKU (ヒナク)

> "One name. An infinite void. No light at the end."

A personal AI assistant designed for a single user (the owner) that runs locally on an HP V15 laptop (AMD Ryzen 7, NVIDIA RTX 4050 6 GB VRAM), remembers the owner across sessions, uses a hybrid local + API router, and periodically trains a small model of its own.

---

## Current Status

- **Step 1 completed**: Basic chat window working with the local Ollama model (`qwen3.5:4b`) from `config/settings.yaml`.

---

## Prerequisites

- Windows 11 / 10
- Python 3.11+
- [Ollama](https://ollama.com/) running locally with `qwen3.5:4b` pulled:
  ```powershell
  ollama pull qwen3.5:4b
  ```

---

## Setup

1. Create and activate virtual environment:
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

2. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```

---

## Running HINAKU

### 1. Launch Desktop App (pywebview GUI)
```powershell
.\venv\Scripts\python.exe run_desktop.py
```

### 2. Run Backend Server Only (Browser / Dev Mode)
```powershell
.\venv\Scripts\python.exe run_desktop.py --server-only
```
Then navigate to `http://127.0.0.1:8000` in your browser.

---

## Running Tests

Run the full pytest suite:
```powershell
.\venv\Scripts\python.exe -m pytest tests/ -v
```

---

## Configuration

Settings are defined in `config/settings.yaml`:
- **App**: Window hotkey, reduced motion preferences.
- **Local model**: Ollama host URL and default model name (`qwen3.5:4b`).
- **Personality**: `config/hinaku_persona.md`.
