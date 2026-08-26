# 🟢 Jarvis AI — Personal Local Assistant

<div align="center">

![Jarvis Banner](https://img.shields.io/badge/Jarvis-AI%20Assistant-00ff87?style=for-the-badge&logo=openai&logoColor=black)
![Django](https://img.shields.io/badge/Backend-Django%206.1-092E20?style=for-the-badge&logo=django&logoColor=white)
![Ollama](https://img.shields.io/badge/Local%20LLM-Ollama-black?style=for-the-badge&logo=ollama&logoColor=white)
![UI](https://img.shields.io/badge/Theme-Matrix%20Dark-050807?style=for-the-badge&logo=css3&logoColor=00ff87)

<p align="center">
  <b>⚡ Lightning-Fast • 🔒 100% Private & Local • 🎨 Sleek Matrix Aesthetic • 💬 Real-Time Streaming</b>
</p>

</div>

---

## ⚡ Super Easy 1-Click Launch (Recommended)

Just **double-click** the file below in the project directory:

```bash
👉 run.bat
```

> **What happens automatically?**
> 1. ⚙️ Validates your Python environment.
> 2. 🗄️ Applies database migrations.
> 3. 🌐 Starts the Django server.
> 4. 🚀 **Opens your default browser straight to [http://127.0.0.1:8000/](http://127.0.0.1:8000/)**!

---

## 💻 Alternative Terminal Launch

Prefer the command line? Run any of the following:

### 🔹 Using PowerShell:
```powershell
.\run.ps1
```

### 🔹 Using Python Directly:
```powershell
& ".\django\Scripts\python.exe" "backend\manage.py" runserver
```

---

## 📋 Prerequisites & Setup

1. **🤖 Ollama Running Locally**:
   - Download & start [Ollama](https://ollama.com).
   - Pull the default model (or your preferred alternative):
     ```bash
     ollama pull jarvis-ft:latest
     ```
     *Fallback models also supported:* `qwen3:1.7b` | `llama3.2:3b`

2. **🐍 Python Virtual Environment**:
   - The pre-configured `django/` environment is included out-of-the-box.

---

## 📁 Project Architecture

```
Django YT/
│
├── ⚡ run.bat               # 1-Click launcher (Starts server + auto-opens browser)
├── 📜 run.ps1               # PowerShell launcher script
├── 📖 README.md             # Project documentation
│
├── 🎨 frontend/             # [FRONTEND] Client-side assets & presentation
│   ├── static/
│   │   ├── css/style.css    # Matrix Dark glowing theme & layout styling
│   │   └── js/chat.js       # Real-time SSE streaming & Markdown renderer
│   └── templates/
│       └── todo/index.html  # Clean semantic HTML interface
│
├── ⚙️ backend/              # [BACKEND] Core server logic & database
│   ├── manage.py            # Django CLI management script
│   ├── db.sqlite3           # Indexed SQLite database
│   ├── ai/                  # Project configuration (settings.py, urls.py)
│   └── todo/                # App views, models, admin & LLM pipeline
│
└── 🐍 django/               # Python Virtual Environment
```

---

## ✨ Key Features

| Feature | Description |
| :--- | :--- |
| ⚡ **Real-Time SSE Streaming** | Live token-by-token response generation with zero lag |
| 🧠 **Bounded Context Memory** | Auto-managed history window to keep response times blazing fast |
| 🎨 **Matrix Neon Design** | Deep dark mode with cyber emerald glow effects & smooth micro-animations |
| 📋 **Syntax Code Highlighting** | Markdown parser with one-click code copy buttons |
| 🗄️ **Persistent Conversations** | Full chat history saved with indexed fast database lookups |

---

<div align="center">
  <sub>Engineered with ❤️ for seamless, private local AI interaction.</sub>
</div>
