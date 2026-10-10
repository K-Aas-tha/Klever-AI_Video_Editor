# Klever AI Video Editor

Klever is a local web app for turning long videos into shorter edits. Upload a video, choose whether to remove silence and add topic intro slides, generate an edited video, then preview and download the result.

## Requirements

- Git
- [Bun](https://bun.sh/) for the frontend
- Python 3.13 for the backend and Whisper
- FFmpeg and ffprobe available on `PATH`
- Ollama with the `llama3.2` model for generating topic-slide titles; it is optional when topic slides are disabled

## Clone

```powershell
git clone https://github.com/K-Aas-tha/Klever-AI_Video_Editor.git
cd Klever-AI_Video_Editor
```

## Set Up the Backend

In a PowerShell terminal from the repository root:

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Start the API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Keep this terminal open. The first start may download the Whisper model. CPU systems use `tiny` by default; CUDA systems use `base`. To choose a different Whisper model, set `KLEVER_WHISPER_MODEL` before starting the backend, for example:

```powershell
$env:KLEVER_WHISPER_MODEL = "base"
```

To generate topic slides or use Ollama-assisted segment selection, install and start Ollama, then download the model:

```powershell
ollama pull llama3.2
```

Ollama is required when topic slides are enabled so each slide can show a concise title for its transcript section. If topic slides are disabled and Ollama is unavailable, the backend keeps the recognized speech segments by default.

## Set Up the Frontend

Open a second terminal at the repository root:

```powershell
cd front_end
bun install
bun run dev -- --host 127.0.0.1
```

Open the local URL printed by Bun/Vite, typically `http://127.0.0.1:8080/`. The frontend expects the backend at `http://localhost:8000`.

## Use the Editor

1. Choose **Create clips**, then select a video or drag it into the upload area. Videos must be smaller than 500 MB.
2. Review the editing prompt and choose whether to remove silence or add topic intro slides.
3. Select **Generate Video** and follow the progress in the editor.
4. Preview the result and select **Download Edited Video**.

The backend API and interactive documentation are available at `http://127.0.0.1:8000/` and `http://127.0.0.1:8000/docs`.

## Author

### Aastha Nayak & Sandhya Tiwari

**Machine Learning • Python • Natural Language Processing • FastAPI**

💡 Open to collaboration on Machine Learning, Python, and AI projects.

[![GitHub](https://img.shields.io/badge/GitHub-K--Aas--tha-181717?style=for-the-badge&logo=github)](https://github.com/K-Aas-tha)
[![Email](https://img.shields.io/badge/Email-Contact-red?style=for-the-badge&logo=gmail)](mailto:aasthanayak161@gmail.com)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-blue?style=for-the-badge&logo=linkedin)](https://www.linkedin.com/in/aastha-nayak-76bb7a34b)
