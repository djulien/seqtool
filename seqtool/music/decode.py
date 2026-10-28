"""Streaming audio decode to mono float32 at a fixed analysis rate.

ffmpeg (any format) is preferred; plain .wav falls back to the stdlib `wave`
module with linear-interpolation resampling. Either way the caller receives
bounded-size chunks, never the whole song.
"""
from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path
from typing import Iterator

import numpy as np

from ..common.deps import need_exe

SR = 24000            # analysis rate: 50 ms = 1200 samples, 10 ms = 240 samples exactly
CHUNK = SR * 10       # 10 s per chunk


def probe(path: Path) -> dict:
    ffprobe = need_exe("ffprobe", purpose="reading audio metadata")
    if ffprobe:
        out = subprocess.check_output(
            [ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries",
             "stream=sample_rate,channels,codec_name,bits_per_sample:format=duration,format_name",
             "-of", "json", str(path)], text=True)
        j = json.loads(out)
        st, fm = j["streams"][0], j["format"]
        info = {"duration": float(fm["duration"]), "sample_rate": int(st["sample_rate"]),
                "channels": int(st["channels"]), "codec": st.get("codec_name", ""),
                "format": fm.get("format_name", "")}
        if int(st.get("bits_per_sample") or 0):
            info["bit_depth"] = int(st["bits_per_sample"])
        return info
    with wave.open(str(path)) as w:
        return {"duration": w.getnframes() / w.getframerate(), "sample_rate": w.getframerate(),
                "channels": w.getnchannels(), "bit_depth": 8 * w.getsampwidth(), "format": "wav"}


def _wav_chunks(path: Path) -> Iterator[np.ndarray]:
    with wave.open(str(path)) as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(sw)
        if dtype is None:
            raise ValueError(f"unsupported WAV sample width {sw}")
        scale = {1: 128.0, 2: 32768.0, 4: 2147483648.0}[sw]
        pos_in, pos_out = 0, 0          # running sample positions for gapless resampling
        tail = np.zeros(0, dtype=np.float32)
        while True:
            raw = w.readframes(sr * 10)
            if not raw:
                break
            x = np.frombuffer(raw, dtype=dtype).astype(np.float32)
            if sw == 1:
                x -= 128
            x = (x / scale).reshape(-1, ch).mean(axis=1)
            x = np.concatenate([tail, x])
            t_end = (pos_in + len(x) - 1) / sr
            n_out = int(np.floor(t_end * SR)) - pos_out
            if n_out > 0:
                t = (pos_out + np.arange(n_out)) / SR
                yield np.interp(t, (pos_in + np.arange(len(x))) / sr, x).astype(np.float32)
                pos_out += n_out
            tail = x[-1:]
            pos_in += len(x) - 1


def chunks(path: Path) -> Iterator[np.ndarray]:
    ffmpeg = need_exe("ffmpeg", purpose="decoding audio (WAV works without it)")
    if ffmpeg is None:
        if path.suffix.lower() != ".wav":
            raise RuntimeError("ffmpeg is required for non-WAV input")
        yield from _wav_chunks(path)
        return
    proc = subprocess.Popen([ffmpeg, "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR),
                             "-f", "f32le", "-"], stdout=subprocess.PIPE)
    try:
        while True:
            buf = proc.stdout.read(CHUNK * 4)
            if not buf:
                break
            yield np.frombuffer(buf, dtype=np.float32)
    finally:
        proc.stdout.close()
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed decoding {path}")
