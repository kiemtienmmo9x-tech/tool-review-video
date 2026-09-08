"""FFmpeg rendering pipeline for licensed source footage.

This module deliberately uses standard loudness/format processing only. It does
not alter audio to evade copyright matching, moderation, or platform detection.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

API_URL = "https://api.ai33.pro/v3/text-to-speech"
TASK_URL = "https://api.ai33.pro/v1/task/{task_id}"
DEFAULT_AI_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
NORMAL_AUDIO_FILTER = "aformat=channel_layouts=stereo,loudnorm=I=-16:TP=-1.5:LRA=11"
ENDING_QUESTION = "Was the officer's reaction fully justified, or did the confrontation escalate too far? Let us know below."
REPLACEMENTS = {"kill himself": "forcing an extreme standoff", "suicide": "combative escalation", "shot dead": "the threat was neutralized", "executed": "concluded at the scene"}


class FlowValidationError(ValueError):
    """Raised when FLOW_DATA misses the supported contract."""


def to_seconds(value: str) -> float:
    try:
        hours, minutes, seconds = value.split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except (ValueError, AttributeError) as error:
        raise FlowValidationError(f"Mốc thời gian không hợp lệ: {value!r}") from error


def time_range(value: str) -> tuple[float, float]:
    try:
        start, end = (to_seconds(part) for part in value.split("-"))
    except ValueError as error:
        raise FlowValidationError(f"Khoảng thời gian không hợp lệ: {value!r}") from error
    if end <= start:
        raise FlowValidationError(f"Điểm kết thúc phải sau điểm bắt đầu: {value!r}")
    return start, end


def to_timestamp(seconds: float) -> str:
    """Format a non-negative offset for the FLOW_DATA time contract."""
    seconds = max(0, round(seconds, 3))
    hours, remainder = divmod(int(seconds), 3600)
    minutes, whole_seconds = divmod(remainder, 60)
    fraction = seconds - int(seconds)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds + fraction:06.3f}".rstrip("0").rstrip(".")


def set_hook_duration(flow: dict[str, Any], part_name: str, seconds: float) -> None:
    """Preserve the hook start and let the editor choose its duration."""
    start, _ = time_range(flow[part_name]["hook"]["time"])
    flow[part_name]["hook"]["time"] = f"{to_timestamp(start)}-{to_timestamp(start + seconds)}"


def validate_flow(flow: dict[str, Any]) -> None:
    for part_name in ("part1", "part2"):
        part = flow.get(part_name)
        if not isinstance(part, dict) or not isinstance(part.get("sequence"), list):
            raise FlowValidationError(f"{part_name} cần có hook và sequence.")
        hook = part.get("hook", {})
        start, end = time_range(hook.get("time", ""))
        if not 2 <= end - start <= 30:
            raise FlowValidationError(f"{part_name}.hook phải dài từ 2 đến 30 giây.")
        for index, block in enumerate(part["sequence"], 1):
            if block.get("type") not in {"block", "cliffhanger"}:
                raise FlowValidationError(f"{part_name}.sequence[{index}].type không hợp lệ.")
            if not isinstance(block.get("vo_text"), str) or not block["vo_text"].strip():
                raise FlowValidationError(f"{part_name}.sequence[{index}] cần vo_text.")
            if not isinstance(block.get("vo_cuts"), list) or not block["vo_cuts"]:
                raise FlowValidationError(f"{part_name}.sequence[{index}] cần ít nhất một vo_cut.")
            time_range(block.get("dialogue_time", ""))
            for cut in block.get("vo_cuts", []):
                if not isinstance(cut, list) or len(cut) != 2 or to_seconds(cut[0]) < 0 or float(cut[1]) <= 0:
                    raise FlowValidationError(f"vo_cuts của {part_name}.sequence[{index}] không hợp lệ.")


def policy_safe_text(text: str) -> str:
    for source, replacement in REPLACEMENTS.items():
        text = re.sub(re.escape(source), replacement, text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:f\*+k|s\*+t)\b", "Units respond Code 3", text, flags=re.IGNORECASE)
    return text


def generate_flow(transcript: str, hook_seconds: float, api_key: str, model: str, api_url: str = DEFAULT_AI_URL, provider: str = "OpenAI-compatible") -> dict[str, Any]:
    """Ask an OpenAI-compatible model for editable FLOW_DATA from a transcript.

    The endpoint and model are configurable to support a user's own compatible
    provider. The model response is validated before it reaches the renderer.
    """
    if not api_key:
        raise RuntimeError("Nhập AI API key để tạo FLOW_DATA.")
    schema = {"part1": {"hook": {"time": "HH:MM:SS-HH:MM:SS", "has_gunshot": False}, "sequence": [{"type": "block", "vo_text": "", "vo_cuts": [["HH:MM:SS", 3]], "dialogue_time": "HH:MM:SS-HH:MM:SS", "has_gunshot": False}]}, "part2": {"hook": {"time": "HH:MM:SS-HH:MM:SS", "has_gunshot": False}, "sequence": []}}
    prompt = f"""Create a two-part FLOW_DATA JSON plan from this transcript. Return JSON only, with no Markdown. Use exactly the schema shape below. Each hook must be {hook_seconds} seconds long. Use source timestamps found in the transcript; do not invent facts. Keep VO factual, non-graphic, and remove profanity. Part 2's last VO should end with this exact question: {ENDING_QUESTION}\nSchema: {json.dumps(schema)}\nTranscript:\n{transcript}"""
    if provider == "Gemini":
        url = api_url.format(model=model)
        payload = json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}}).encode()
        headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    else:
        url = api_url
        payload = json.dumps({"model": model, "messages": [{"role": "system", "content": "You are a careful video editor. Return valid JSON only."}, {"role": "user", "content": prompt}], "temperature": 0.2}).encode()
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            response_data = json.loads(response.read())
        if provider == "Gemini":
            content = response_data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            content = response_data["choices"][0]["message"]["content"]
        flow = json.loads(content.removeprefix("```json").removesuffix("```").strip())
        for part_name in ("part1", "part2"):
            set_hook_duration(flow, part_name, hook_seconds)
        validate_flow(flow)
        return flow
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError, IndexError, json.JSONDecodeError, FlowValidationError) as error:
        raise RuntimeError(f"AI không tạo được FLOW_DATA hợp lệ: {error}") from error


def _find_url(value: Any) -> str | None:
    if isinstance(value, str) and value.startswith("http") and ("audio" in value or value.endswith((".mp3", ".wav", ".m4a"))):
        return value
    if isinstance(value, dict):
        for nested in value.values():
            found = _find_url(nested)
            if found:
                return found
    if isinstance(value, list):
        for nested in value:
            found = _find_url(nested)
            if found:
                return found
    return None


def get_tts_audio(text: str, out_path: Path, api_key: str, voice_id: str, speed: float) -> None:
    if not api_key:
        raise RuntimeError("Nhập AI33 API key để tạo voiceover.")
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
    try:
        payload = json.dumps({"text": policy_safe_text(text), "voice_id": voice_id, "speed": str(speed), "with_transcript": "false"}).encode()
        request = urllib.request.Request(API_URL, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=30) as response:
            created = json.loads(response.read())
        task_id = created.get("task_id") or created.get("data", {}).get("task_id")
        if not task_id:
            raise RuntimeError("AI33 không trả về task_id.")
        for _ in range(40):
            time.sleep(2)
            request = urllib.request.Request(TASK_URL.format(task_id=task_id), headers=headers)
            with urllib.request.urlopen(request, timeout=30) as response:
                status = json.loads(response.read())
            audio_url = _find_url(status)
            if audio_url:
                with urllib.request.urlopen(audio_url, timeout=60) as audio:
                    out_path.write_bytes(audio.read())
                return
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as error:
        raise RuntimeError(f"Không thể gọi AI33 TTS: {error}") from error
    raise RuntimeError("AI33 TTS chưa hoàn tất sau thời gian chờ.")


def run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"FFmpeg không thể render: {result.stderr[-700:]}")


def clip(input_path: Path, start: float, end: float, output: Path, audio_filter: str | None = NORMAL_AUDIO_FILTER) -> None:
    command = ["ffmpeg", "-y", "-ss", str(start), "-to", str(end), "-i", str(input_path), "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-c:a", "aac"]
    if audio_filter:
        command += ["-af", audio_filter]
    run(command + [str(output)])


def concat(paths: list[Path], output: Path) -> None:
    listing = output.with_suffix(".txt")
    listing.write_text("".join(f"file '{path.resolve()}'\n" for path in paths), encoding="utf-8")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(output)])


def vo_clip(input_path: Path, cuts: list[list[Any]], voice: Path, output: Path, workspace: Path) -> None:
    visuals: list[Path] = []
    for index, (start, seconds) in enumerate(cuts):
        visual = workspace / f"cut-{len(visuals)}.mp4"
        clip(input_path, to_seconds(start), to_seconds(start) + float(seconds), visual, None)
        visuals.append(visual)
    visual_source = visuals[0] if len(visuals) == 1 else workspace / "vo-visuals.mp4"
    if len(visuals) > 1:
        concat(visuals, visual_source)
    run(["ffmpeg", "-y", "-i", str(visual_source), "-i", str(voice), "-map", "0:v:0", "-map", "1:a:0", "-shortest", "-c:v", "libx264", "-c:a", "aac", "-b:a", "192k", str(output)])


def render_parts(input_video: Path, flow: dict[str, Any], output_dir: Path, api_key: str, voice_id: str, speed: float) -> dict[str, Path]:
    """Render the two configured parts. VO sections intentionally omit source audio."""
    outputs: dict[str, Path] = {}
    for part_name in ("part1", "part2"):
        work = output_dir / part_name
        work.mkdir()
        part, clips = flow[part_name], []
        start, end = time_range(part["hook"]["time"])
        hook = work / "00-hook.mp4"
        clip(input_video, start, end, hook)
        clips.append(hook)
        for index, block in enumerate(part["sequence"], 1):
            text = policy_safe_text(block["vo_text"])
            if part_name == "part2" and index == len(part["sequence"]):
                text = f"{text.rstrip()} {ENDING_QUESTION}"
            voice, voiced = work / f"{index:02d}-voice.mp3", work / f"{index:02d}-vo.mp4"
            get_tts_audio(text, voice, api_key, voice_id, speed)
            vo_clip(input_video, block.get("vo_cuts", []), voice, voiced, work)
            clips.append(voiced)
            dialogue = work / f"{index:02d}-dialogue.mp4"
            dialogue_start, dialogue_end = time_range(block["dialogue_time"])
            clip(input_video, dialogue_start, dialogue_end, dialogue)
            clips.append(dialogue)
        output = output_dir / f"{part_name}.mp4"
        concat(clips, output)
        outputs[part_name] = output
    return outputs
