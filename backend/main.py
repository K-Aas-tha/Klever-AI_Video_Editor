import json
import os
import math
import re
import uuid
import shutil
import subprocess
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import torch
except ImportError:
    torch = None

try:
    import whisper
except ImportError:
    whisper = None

app = FastAPI(title="Klever AI Video Editor")
allowed_origins = [
    origin.strip()
    for origin in os.getenv("KLEVER_ALLOWED_ORIGINS", "*").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

JOBS_DIR = os.getenv("KLEVER_JOBS_DIR", os.path.join(os.path.dirname(__file__), "jobs"))
OLLAMA_URL = os.getenv("KLEVER_OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("KLEVER_OLLAMA_MODEL", "llama3.2")
job_states: dict[str, dict[str, Any]] = {}

if torch is not None:
    device = "cuda" if torch.cuda.is_available() else "cpu"
else:
    device = "cpu"
print(f"Device is {device}")
whisper_model_name = os.getenv("KLEVER_WHISPER_MODEL", "base" if device == "cuda" else "tiny")
print(f"Loading Whisper model: {whisper_model_name}")
whisper_model = whisper.load_model(whisper_model_name, device=device) if whisper is not None else None
if whisper_model is not None:
    print("whisper model is loaded")
else:
    print("Warning: whisper model is unavailable. Install whisper to enable transcription.")

whisper_transcribe_options = {"fp16": device == "cuda", "verbose": False}
if device == "cpu":
    whisper_transcribe_options.update(
        temperature=0.0,
        condition_on_previous_text=False,
        beam_size=1,
    )


def format_subtitle(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    sec = int(seconds % 60)
    milliseconds = int((seconds - int(seconds)) * 1000)
    return f"{hours:02}:{minutes:02}:{sec:02},{milliseconds:03}"


def create_sub(segments, output_path):
    """Create subtitles using original Whisper timestamps."""
    with open(output_path, "w", encoding="utf-8") as f:
        for i, segment in enumerate(segments, start=1):
            start = format_subtitle(segment["start"])
            end = format_subtitle(segment["end"])
            text = segment["text"].strip()

            f.write(f"{i}\n")
            f.write(f"{start} --> {end}\n")
            f.write(f"{text}\n\n")


def create_edit_sub(
    keep_segments,
    output_path,
    slide_indices=None,
    slide_duration=0.0,
    preserved_gap_indices=None,
):
    """Adjust timestamps to match the edited video timeline."""
    current_time = 0.0
    slide_indices = slide_indices or set()
    preserved_gap_indices = preserved_gap_indices or set()
    with open(output_path, "w", encoding="utf-8") as f:
        for index, segment in enumerate(keep_segments):
            if index in slide_indices:
                current_time += slide_duration
            if index in preserved_gap_indices:
                gap = segment["start"] - keep_segments[index - 1]["end"]
                current_time += max(gap, 0.0)

            i = index + 1
            original_start = segment["start"]
            original_end = segment["end"]
            duration = original_end - original_start
            new_start = current_time
            new_end = current_time + duration
            start = format_subtitle(new_start)
            end = format_subtitle(new_end)
            text = segment["text"].strip()
            f.write(f"{i}\n")
            f.write(f"{start} --> {end}\n")
            f.write(f"{text}\n\n")
            current_time += duration


def group_kept_segments(keep_segments, slide_indices, max_gap=0.35):
    """Combine nearby segments to reduce FFmpeg startup and encode overhead."""
    groups = []
    preserved_gap_indices = set()
    for index, segment in enumerate(keep_segments):
        if not groups or index in slide_indices:
            groups.append([(index, segment)])
            continue

        previous_segment = groups[-1][-1][1]
        gap = float(segment["start"]) - float(previous_segment["end"])
        if gap <= max_gap:
            groups[-1].append((index, segment))
            if gap > 0:
                preserved_gap_indices.add(index)
        else:
            groups.append([(index, segment)])

    return groups, preserved_gap_indices


def detect_visuals(video_path, start, end):
    """Return True if the frame at the midpoint is visually useful."""
    if cv2 is None:
        return True

    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        return True

    fps = capture.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        capture.release()
        return True

    middle_time = (start + end) / 2
    capture.set(cv2.CAP_PROP_POS_MSEC, middle_time * 1000)
    success, frame = capture.read()
    capture.release()

    if not success or frame is None:
        return True

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    brightness = gray.mean()
    print(f"OpenCV brightness: {brightness:.2f}")
    return brightness > 20


@app.get("/")
def home():
    return {
        "message": "Klever AI Video Editor API",
        "status": "running",
    }


@app.post("/edit")
async def edit_video(file: UploadFile = File(...)):
    job_id = str(uuid.uuid4())
    os.makedirs("jobs", exist_ok=True)
    work_dir = os.path.join("jobs", job_id)
    os.makedirs(work_dir, exist_ok=True)

    safe_name = os.path.basename(file.filename or "upload.mp4")
    input_video = os.path.join(work_dir, safe_name)

    with open(input_video, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    print("New video received")
    print(f"File: {safe_name}")

    print("\nTranscribing video...")
    if whisper_model is None:
        return {"error": "Whisper is not installed or available. Install the required dependencies first."}
    result = whisper_model.transcribe(input_video, **whisper_transcribe_options)
    segments = result.get("segments", [])
    print(f"Found {len(segments)} transcript segments")

    original_sub_path = os.path.join(work_dir, "original_sub.srt")
    create_sub(segments, original_sub_path)

    decisions = []
    batch_size = 8
    print("AI analysis in progress...")

    for batch_start in range(0, len(segments), batch_size):
        batch = segments[batch_start : batch_start + batch_size]
        print(f"Processing batch: {batch_start + 1}-{batch_start + len(batch)} of {len(segments)}")

        segment_text = ""
        for local_index, segment in enumerate(batch):
            global_index = batch_start + local_index + 1
            segment_text += f"SEGMENT {global_index}: {segment['text'].strip()} "

        prompt = f"""
        You are editing a spoken video for a concise, coherent cut.
        Remove greetings, filler, false starts, repeated points, redundant examples,
        long pauses, meta-commentary, tangents, and setup that adds no information.
        Keep unique facts, key explanations, necessary steps, and context required
        to understand them. Prefer REMOVE for low-value or repetitive segments;
        keep a segment only when removing it would lose an important idea or make
        the remaining explanation confusing.

        Return exactly one line for every input segment, using only this format:
        SEGMENT N: KEEP
        SEGMENT N: REMOVE
        Do not add explanations, headings, or other text.

        {segment_text}
        """

        ai_res = ""
        try:
            response = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=120,
            )
            response.raise_for_status()
            ai_res = response.json().get("response", "").strip()
            print("\nOllama response:")
            print(ai_res)
        except Exception as exc:
            print(f"Ollama error: {exc}")
            ai_res = ""

        batch_decisions = {}
        for line in ai_res.splitlines():
            line = line.strip().upper()
            if not line.startswith("SEGMENT"):
                continue
            try:
                parts = line.split(":", 1)
                segment_number = int(parts[0].replace("SEGMENT", "").strip())
                decision = parts[1].strip()
                if decision.startswith("REMOVE"):
                    batch_decisions[segment_number] = "REMOVE"
                elif decision.startswith("KEEP"):
                    batch_decisions[segment_number] = "KEEP"
            except Exception:
                continue

        for local_index, segment in enumerate(batch):
            global_index = batch_start + local_index + 1
            decision = batch_decisions.get(global_index, "KEEP")
            decisions.append({
                "start": segment["start"],
                "end": segment["end"],
                "text": segment["text"].strip(),
                "decision": decision,
            })
            print(f"Segment {global_index}: {decision}")

    keep_segments = [segment for segment in decisions if segment["decision"] == "KEEP"]
    print(f"\nKEEP segments: {len(keep_segments)}")
    print(f"REMOVE segments: {len(decisions) - len(keep_segments)}")

    subtitle_path = os.path.join(work_dir, "subtitles.srt")
    create_edit_sub(keep_segments, subtitle_path)
    print(f"\nSubtitles created: {subtitle_path}")

    temp_dir = os.path.join(work_dir, "temp_clips")
    os.makedirs(temp_dir, exist_ok=True)
    clip_files = []
    print("Creating clips...")

    for i, segment in enumerate(keep_segments):
        start = segment["start"]
        end = segment["end"]
        clip_path = os.path.join(temp_dir, f"clip_{i:03d}.mp4")
        print(f"Clip {i + 1}/{len(keep_segments)} [{start:.2f}s -> {end:.2f}s]")
        command = [
            "ffmpeg",
            "-y",
            "-ss",
            str(start),
            "-to",
            str(end),
            "-i",
            input_video,
            "-map",
            "0:v:0?",
            "-map",
            "0:a:0?",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-preset",
            "ultrafast",
            clip_path,
        ]
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        clip_files.append(clip_path)

    if not clip_files:
        return {"error": "No clips were selected"}

    concat_file = os.path.join(temp_dir, "concat.txt")
    with open(concat_file, "w", encoding="utf-8", newline="\n") as f:
        for clip in clip_files:
            clip_name = os.path.basename(clip)
            f.write(f"file '{clip_name}'\n")

    print("Concat file created")
    print(os.path.abspath(concat_file))
    print("Concat contents:")
    with open(concat_file, "r", encoding="utf-8") as f:
        print(f.read())

    edited_video = os.path.join(work_dir, "edited_video.mp4")
    print("Joining clips...")
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        os.path.abspath(concat_file),
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-preset",
        "ultrafast",
        edited_video,
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    final_video = os.path.join(work_dir, "final_video.mp4")
    print("Adding subtitles...")
    subtitle_filter = subtitle_path.replace("\\", "/")
    command = [
        "ffmpeg",
        "-y",
        "-i",
        edited_video,
        "-vf",
        f"subtitles='{subtitle_filter}'",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-preset",
        "ultrafast",
        final_video,
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    print("\n================================")
    print("Video editing complete")
    print("================================")
    print(f"Final video: {final_video}")
    print(f"Subtitles: {subtitle_path}")
    return FileResponse(final_video, media_type="video/mp4", filename="edited_video.mp4")


def update_job(job_id, **updates):
    job_states[job_id].update(updates)


def run_media_command(command):
    if shutil.which(command[0]) is None:
        raise RuntimeError(f"{command[0]} is required but was not found on PATH.")

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        error = result.stderr.strip()[-2000:]
        raise RuntimeError(error or f"{command[0]} exited with code {result.returncode}.")


def inspect_video(video_path):
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise RuntimeError("ffprobe is required but was not found on PATH.")

    result = subprocess.run(
        [
            ffprobe,
            "-v", "error",
            "-show_entries", "format=duration:stream=codec_type,duration",
            "-of", "json",
            video_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        error = result.stderr.strip()[-1000:]
        raise ValueError(error or "FFmpeg could not read this video file.")

    try:
        metadata = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("FFmpeg returned invalid video metadata.") from exc

    streams = metadata.get("streams") or []
    if not any(stream.get("codec_type") == "video" for stream in streams):
        raise ValueError("The uploaded file does not contain a video stream.")

    durations = []
    format_duration = (metadata.get("format") or {}).get("duration")
    if format_duration is not None:
        durations.append(format_duration)
    durations.extend(
        stream["duration"]
        for stream in streams
        if stream.get("codec_type") == "video" and stream.get("duration") is not None
    )
    valid_durations = []
    for value in durations:
        try:
            parsed_duration = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed_duration) and parsed_duration > 0:
            valid_durations.append(parsed_duration)
    if not valid_durations:
        raise ValueError("The video has an invalid duration.")
    duration = max(valid_durations)

    has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    return duration, has_audio


def create_topic_slide(work_dir, topic_number, title):
    image = Image.new("RGB", (1280, 720), (19, 27, 40))
    draw = ImageDraw.Draw(image)
    font_path = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "arial.ttf")
    try:
        title_font = ImageFont.truetype(font_path, 54)
    except OSError:
        title_font = ImageFont.load_default()

    title = title.encode("utf-8", "replace").decode("utf-8")[:120]
    words = title.split()
    lines = []
    line = ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=title_font) > 1080 and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)

    draw.rectangle((0, 0, 18, 720), fill=(236, 91, 76))
    draw.multiline_text(
        (76, 210),
        "\n".join(lines[:3]) or f"Section {topic_number}",
        fill=(246, 248, 251),
        font=title_font,
        spacing=18,
    )

    slide_path = os.path.join(work_dir, f"topic_{topic_number}.png")
    image.save(slide_path)
    return slide_path


def generate_topic_titles(topic_texts):
    topic_sources = "\n\n".join(
        f"TOPIC {topic_number} SOURCE:\n{text[:3000]}"
        for topic_number, text in enumerate(topic_texts, start=1)
    )
    expected_lines = "\n".join(
        f"TOPIC {topic_number}: <2-6 word title>"
        for topic_number in range(1, len(topic_texts) + 1)
    )
    title_prompt = f"""
Identify the main subject of each transcript section below. Write one concise
title of 2 to 6 words per section. Do not quote the transcript or add explanations.

Return exactly {len(topic_texts)} lines in this format, without omitting a topic:
{expected_lines}

{topic_sources}
"""
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": title_prompt,
                "stream": False,
                "options": {"temperature": 0, "num_predict": max(64, 24 * len(topic_texts))},
            },
            timeout=120,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not generate topic slide titles with Ollama: {exc}") from exc

    try:
        response_payload = response.json()
    except ValueError as exc:
        raise RuntimeError("Ollama returned invalid data while generating topic slide titles.") from exc

    if not isinstance(response_payload, dict) or not isinstance(response_payload.get("response"), str):
        raise RuntimeError("Ollama did not return topic slide titles.")

    titles = {}
    response_lines = [
        line.strip().strip("\"'").strip()
        for line in response_payload["response"].splitlines()
        if line.strip()
    ]
    for line in response_lines:
        match = re.fullmatch(r"\s*(?:TOPIC\s+)?(\d+)\s*[:.)-]\s*(.+?)\s*", line, re.I)
        if match:
            topic_number = int(match.group(1))
            title = match.group(2).strip().strip("\"'").strip()
            if title and len(title.split()) <= 8:
                titles[topic_number] = title

    expected_topics = set(range(1, len(topic_texts) + 1))
    if not titles and len(response_lines) == len(topic_texts):
        titles = {
            topic_number: title
            for topic_number, title in enumerate(response_lines, start=1)
            if title and len(title.split()) <= 8
        }
    if set(titles) != expected_topics:
        raise RuntimeError("Ollama returned incomplete or invalid topic slide titles.")

    return [titles[topic_number] for topic_number in sorted(expected_topics)]


def process_video_job(job_id, prompt, remove_silence, insert_slides, slide_duration):
    state = job_states[job_id]
    work_dir = state["work_dir"]
    input_video = state["input_video"]

    try:
        video_duration, source_has_audio = inspect_video(input_video)
        if source_has_audio and whisper_model is None:
            raise RuntimeError(
                "Whisper is unavailable in this Python environment. Install backend requirements "
                "using the project's Python 3.13 environment, then restart the backend."
            )

        segments = []
        if source_has_audio:
            update_job(job_id, progress=5, step_message="Transcribing audio with Whisper...")
            transcript = whisper_model.transcribe(input_video, **whisper_transcribe_options)
            segments = transcript.get("segments", [])
        has_speech = bool(segments)
        if not has_speech:
            segments = [{"start": 0.0, "end": video_duration, "text": ""}]

        if has_speech:
            create_sub(segments, os.path.join(work_dir, "original_sub.srt"))
        decisions = ["KEEP"] * len(segments)

        if remove_silence and has_speech:
            batch_size = 32
            for batch_start in range(0, len(segments), batch_size):
                batch = segments[batch_start:batch_start + batch_size]
                segment_text = "\n".join(
                    f"SEGMENT {batch_start + local_index + 1}: {segment['text'].strip()}"
                    for local_index, segment in enumerate(batch)
                )
                decision_prompt = f"""
You are editing a spoken video into a concise, coherent cut. Remove greetings,
filler, false starts, repeated points, redundant examples, long pauses,
meta-commentary, tangents, and setup that adds no information. Keep unique facts,
key explanations, necessary steps, and context required to understand them.
Prefer REMOVE for low-value or repetitive segments; keep a segment only when
removing it would lose an important idea or make the remaining explanation confusing.
Apply the user's additional editing instructions: {prompt or 'Make the edit concise while preserving key information.'}

Return exactly one line for every input segment, using only SEGMENT N: KEEP or
SEGMENT N: REMOVE. Do not add explanations, headings, or other text.

{segment_text}
"""
                try:
                    response = requests.post(
                        f"{OLLAMA_URL}/api/generate",
                        json={
                            "model": OLLAMA_MODEL,
                            "prompt": decision_prompt,
                            "stream": False,
                            "options": {"num_predict": batch_size * 8},
                        },
                        timeout=120,
                    )
                    response.raise_for_status()
                    for line in response.json().get("response", "").splitlines():
                        match = re.match(r"\s*SEGMENT\s+(\d+)\s*:\s*(KEEP|REMOVE)", line, re.I)
                        if match:
                            segment_index = int(match.group(1)) - 1
                            if batch_start <= segment_index < batch_start + len(batch):
                                decisions[segment_index] = match.group(2).upper()
                except requests.RequestException as exc:
                    print(f"Ollama unavailable; keeping transcript batch: {exc}")

                progress = 10 + int(25 * min(batch_start + len(batch), len(segments)) / len(segments))
                update_job(
                    job_id,
                    progress=progress,
                    step_message="Selecting useful transcript segments...",
                )

        keep_segments = [
            segment for segment, decision in zip(segments, decisions) if decision == "KEEP"
        ]
        if not keep_segments:
            raise RuntimeError("No transcript segments were selected for the edited video.")

        topic_stride = max(1, math.ceil(len(keep_segments) / 3))
        slide_indices = (
            set(range(0, len(keep_segments), topic_stride))
            if insert_slides and has_speech
            else set()
        )
        render_groups, preserved_gap_indices = group_kept_segments(keep_segments, slide_indices)
        topic_texts = [
            " ".join(segment["text"].strip() for segment in keep_segments[index:index + topic_stride])
            for index in sorted(slide_indices)
        ]
        if topic_texts:
            update_job(job_id, progress=37, step_message="Generating concise topic slide titles...")
            topic_titles = generate_topic_titles(topic_texts)
        else:
            topic_titles = []

        topics = []
        slide_paths = {}
        for topic_number, (segment_index, title) in enumerate(
            zip(sorted(slide_indices), topic_titles),
            start=1,
        ):
            slide_path = create_topic_slide(work_dir, topic_number, title or f"Section {topic_number}")
            slide_paths[segment_index] = slide_path
            topics.append({
                "topic_number": topic_number,
                "title": title or f"Section {topic_number}",
                "timestamp_sec": round(float(keep_segments[segment_index]["start"]), 2),
                "slide_image": f"/api/media/{job_id}/topic_{topic_number}.png",
            })

        update_job(job_id, progress=40, step_message="Rendering video segments...")
        temp_dir = os.path.join(work_dir, "temp_clips")
        os.makedirs(temp_dir, exist_ok=True)
        clip_paths = []
        slide_duration = min(max(float(slide_duration), 0.5), 15.0)
        for group_index, group in enumerate(render_groups):
            first_segment_index, first_segment = group[0]
            last_segment = group[-1][1]
            if first_segment_index in slide_paths:
                slide_video = os.path.join(temp_dir, f"slide_{first_segment_index:04d}.mp4")
                run_media_command([
                    "ffmpeg", "-y", "-loop", "1", "-framerate", "30", "-i", slide_paths[first_segment_index],
                    "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                    "-t", str(slide_duration),
                    "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-ar", "44100", "-ac", "2",
                    "-shortest", slide_video,
                ])
                clip_paths.append(slide_video)

            start = float(first_segment["start"])
            duration = float(last_segment["end"]) - start
            if duration <= 0:
                continue
            clip_path = os.path.join(temp_dir, f"clip_{group_index:04d}.mp4")
            command = ["ffmpeg", "-y", "-ss", str(start), "-i", input_video]
            if not source_has_audio:
                command.extend(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"])
            command.extend([
                "-t", str(duration),
                "-map", "0:v:0",
                "-map", "0:a:0" if source_has_audio else "1:a:0",
                "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p",
                "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-ar", "44100", "-ac", "2",
                "-avoid_negative_ts", "make_zero", clip_path,
            ])
            run_media_command(command)
            clip_paths.append(clip_path)
            progress = 40 + int(40 * (group_index + 1) / len(render_groups))
            update_job(job_id, progress=progress, step_message="Rendering video segments...")

        if not clip_paths:
            raise RuntimeError("FFmpeg could not render any video segments.")

        concat_path = os.path.join(temp_dir, "concat.txt")
        with open(concat_path, "w", encoding="utf-8", newline="\n") as concat_file:
            for clip_path in clip_paths:
                concat_file.write(f"file '{os.path.abspath(clip_path).replace(os.sep, '/')}'\n")

        update_job(job_id, progress=85, step_message="Joining clips and topic slides...")
        joined_video = os.path.join(work_dir, "joined_video.mp4")
        run_media_command([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_path,
            "-c", "copy", joined_video,
        ])

        edited_video = os.path.join(work_dir, "edited_video.mp4")
        if has_speech:
            subtitle_path = os.path.join(work_dir, "subtitles.srt")
            create_edit_sub(
                keep_segments,
                subtitle_path,
                slide_indices,
                slide_duration if insert_slides else 0.0,
                preserved_gap_indices,
            )
            subtitle_filter_path = subtitle_path.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
            try:
                run_media_command([
                    "ffmpeg", "-y", "-i", joined_video,
                    "-vf", f"subtitles='{subtitle_filter_path}'",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", edited_video,
                ])
            except RuntimeError as exc:
                print(f"Subtitle burn-in skipped: {exc}")
                shutil.copy2(joined_video, edited_video)
        else:
            shutil.copy2(joined_video, edited_video)

        thumbnail_path = os.path.join(work_dir, "thumbnail.jpg")
        run_media_command([
            "ffmpeg", "-y", "-i", edited_video, "-frames:v", "1", "-q:v", "2", thumbnail_path,
        ])

        final_duration = sum(
            float(group[-1][1]["end"]) - float(group[0][1]["start"])
            for group in render_groups
        ) + len(slide_indices) * (slide_duration if insert_slides else 0.0)
        summary = {
            "topics_count": len(topics),
            "silences_cut": len(segments) - len(keep_segments),
            "scenes_detected": len(topics),
            "final_duration_sec": round(final_duration, 2),
        }
        update_job(
            job_id,
            status="completed",
            progress=100,
            step_message="Video processing complete.",
            result={
                "edited_video_url": f"/api/media/{job_id}/edited_video.mp4",
                "thumbnail_url": f"/api/media/{job_id}/thumbnail.jpg",
                "topics": topics,
                "summary": summary,
            },
        )
    except Exception as exc:
        print(f"Video processing failed for job {job_id}: {exc}")
        update_job(job_id, status="failed", progress=100, step_message=str(exc))


@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    job_id = str(uuid.uuid4())
    work_dir = os.path.join(JOBS_DIR, job_id)
    os.makedirs(work_dir, exist_ok=False)
    safe_name = os.path.basename(file.filename or "upload.mp4")
    input_video = os.path.join(work_dir, safe_name)
    max_size = 500 * 1024 * 1024
    size = 0

    try:
        with open(input_video, "wb") as output_file:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > max_size:
                    raise HTTPException(status_code=413, detail="Video must be smaller than 500 MB.")
                output_file.write(chunk)
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
    finally:
        await file.close()

    try:
        inspect_video(input_video)
    except ValueError as exc:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported or invalid video file: {exc}",
        ) from exc
    except RuntimeError:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise

    job_states[job_id] = {
        "status": "uploaded",
        "progress": 0,
        "step_message": "Video uploaded and ready for processing.",
        "work_dir": work_dir,
        "input_video": input_video,
    }
    return {"job_id": job_id, "status": "uploaded"}


@app.post("/api/process", status_code=202)
async def start_video_processing(
    background_tasks: BackgroundTasks,
    job_id: str = Form(...),
    prompt: str = Form(""),
    remove_silence: bool = Form(True),
    insert_slides: bool = Form(True),
    slide_duration: float = Form(3.5),
):
    state = job_states.get(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Upload this video before starting processing.")
    if state["status"] == "processing":
        raise HTTPException(status_code=409, detail="This video is already processing.")
    if not 0.5 <= slide_duration <= 15:
        raise HTTPException(status_code=422, detail="Slide duration must be between 0.5 and 15 seconds.")

    state.update(status="processing", progress=1, step_message="Initializing video processing...")
    background_tasks.add_task(
        process_video_job,
        job_id,
        prompt,
        remove_silence,
        insert_slides,
        slide_duration,
    )
    return {"job_id": job_id, "status": "processing"}


@app.get("/api/status/{job_id}")
async def video_job_status(job_id: str):
    state = job_states.get(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Video job was not found.")
    return {
        "job_id": job_id,
        "status": state["status"],
        "progress": state["progress"],
        "step_message": state["step_message"],
        "result": state.get("result"),
    }


@app.get("/api/media/{job_id}/{filename}")
async def video_job_media(job_id: str, filename: str):
    if filename not in {"edited_video.mp4", "thumbnail.jpg"} and not re.fullmatch(
        r"topic_\d+\.png", filename
    ):
        raise HTTPException(status_code=404, detail="Media file was not found.")

    try:
        job_directory = str(uuid.UUID(job_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Video job was not found.") from None

    state = job_states.get(job_id)
    work_dir = state["work_dir"] if state else os.path.join(JOBS_DIR, job_directory)
    media_path = os.path.join(work_dir, filename)
    if not os.path.isfile(media_path):
        raise HTTPException(status_code=404, detail="Media file was not found.")

    media_type = "video/mp4" if filename.endswith(".mp4") else "image/jpeg"
    if filename.endswith(".png"):
        media_type = "image/png"
    return FileResponse(media_path, media_type=media_type)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
