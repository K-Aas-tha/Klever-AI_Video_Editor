# Klever AI Video Editor

Klever is a local web app for turning long videos into shorter edits. Upload a video, choose whether to remove silence and add topic intro slides, generate an edited video, then preview and download the result.

## Requirements

- Git
- [Bun](https://bun.sh/) for the frontend
- Python 3.13 for the backend and Whisper
- FFmpeg and ffprobe available on `PATH`
- Ollama with the `llama3.2` model for AI-assisted segment selection (optional)

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

For Ollama-assisted segment selection, install and start Ollama, then download the model:

```powershell
ollama pull llama3.2
```

Ollama is optional. If it is unavailable, the backend keeps the recognized speech segments by default.

## Set Up the Frontend

Open a second terminal at the repository root:

```powershell
cd front_end
bun install
bun run dev -- --host 127.0.0.1
```

Open the local URL printed by Bun/Vite, typically `http://127.0.0.1:8080/`. The frontend expects the backend at `http://localhost:8000`.

## Deploy the Frontend to Vercel

Import the GitHub repository in Vercel and set **Root Directory** to `front_end`. Vercel should detect the TanStack Start framework automatically. If build settings are requested, use `bun install` as the install command and `bun run build` as the build command; leave the output directory on its automatic setting.

Set this Vercel project environment variable to the public URL of your separately hosted backend:

```text
VITE_API_BASE=https://your-backend-host.example.com
```

Redeploy after adding or changing environment variables. The backend must be hosted on a persistent server with Python 3.13, Whisper, FFmpeg, and ffprobe; video processing is not suitable for a short-lived serverless function. On the backend host, set `FRONTEND_ORIGINS` to your Vercel site origin (scheme and host only), for example `https://your-project.vercel.app`. Multiple allowed origins can be separated by commas.

## Deploy the Backend with Docker

The backend includes a Dockerfile for a persistent container host such as Render. In the host dashboard, create a Docker web service from this repository and set its root directory to `backend`. The host should build from `backend/Dockerfile` and provide its assigned `PORT` environment variable.

Set these backend environment variables:

```text
KLEVER_WHISPER_MODEL=tiny
FRONTEND_ORIGINS=https://your-project.vercel.app
```

Attach persistent storage at `/app/jobs`; this is where uploaded videos and generated output are stored. Copy the backend service's public HTTPS URL into the Vercel project's `VITE_API_BASE` variable, then redeploy the frontend. The first container start may take longer while Whisper downloads its model. Ollama segment selection is optional and only works if the container can reach an Ollama server.

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
