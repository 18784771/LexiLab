from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from lexilab.config.settings import Settings


class TTSUnavailable(RuntimeError):
    pass


@dataclass
class PlaybackResult:
    ok: bool
    message: str = ""


class TTSProvider(Protocol):
    name: str

    def available(self) -> tuple[bool, str]:
        ...

    def synthesize(self, text: str, destination: Path, *, voice: str, rate: float) -> None:
        ...


class FliteTTS:
    """Offline TTS through ffmpeg's built-in libflite (no network needed)."""

    name = "flite"

    def __init__(self) -> None:
        self.ffmpeg = shutil.which("ffmpeg")

    def available(self) -> tuple[bool, str]:
        if not self.ffmpeg:
            return False, "未找到 ffmpeg"
        try:
            result = subprocess.run(
                [self.ffmpeg, "-hide_banner", "-filters"],
                capture_output=True,
                text=True,
                timeout=10,
                stdin=subprocess.DEVNULL,
            )
            if "flite" not in result.stdout:
                return False, "当前 ffmpeg 未编译 libflite"
            return True, "ok"
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"ffmpeg 检查失败: {exc}"

    def synthesize(self, text: str, destination: Path, *, voice: str, rate: float) -> None:
        if not self.ffmpeg:
            raise TTSUnavailable("未找到 ffmpeg")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as fh:
            fh.write(text)
            text_path = Path(fh.name)
        try:
            safe_path = str(text_path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
            voice_name = voice if voice in {"slt", "kal", "awb", "rms", "kal16"} else "slt"
            filters = []
            if abs(rate - 1.0) > 0.01:
                filters = ["-filter:a", f"atempo={max(0.5, min(2.0, rate)):.2f}"]
            command = [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"flite=textfile={safe_path}:voice={voice_name}",
                *filters,
                "-ar",
                "22050",
                "-ac",
                "1",
                str(destination),
            ]
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=45, stdin=subprocess.DEVNULL
            )
            if result.returncode != 0 or not destination.exists() or destination.stat().st_size < 1000:
                raise TTSUnavailable(f"flite 合成失败: {result.stderr.strip()[:300]}")
        finally:
            text_path.unlink(missing_ok=True)


class EspeakTTS:
    name = "espeak"

    def __init__(self) -> None:
        self.command = shutil.which("espeak-ng") or shutil.which("espeak")

    def available(self) -> tuple[bool, str]:
        return (True, "ok") if self.command else (False, "未找到 espeak-ng/espeak")

    def synthesize(self, text: str, destination: Path, *, voice: str, rate: float) -> None:
        if not self.command:
            raise TTSUnavailable("未找到 espeak")
        destination.parent.mkdir(parents=True, exist_ok=True)
        speed = int(175 * max(0.5, min(2.0, rate)))
        voice_name = voice if voice in {"en-us", "en-gb", "slt"} else "en-us"
        args = [self.command, "-v", voice_name, "-s", str(speed), "-w", str(destination), text]
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=45, stdin=subprocess.DEVNULL
        )
        if result.returncode != 0 or not destination.exists():
            raise TTSUnavailable(f"espeak 合成失败: {result.stderr.strip()[:300]}")


class Pyttsx3TTS:
    name = "pyttsx3"

    def available(self) -> tuple[bool, str]:
        try:
            import pyttsx3
        except ImportError:
            return False, "未安装 pyttsx3（可选依赖）"
        try:
            engine = pyttsx3.init()
            engine.getProperty("voices")
            return True, "ok"
        except Exception as exc:
            return False, f"pyttsx3 无法初始化语音后端: {exc}"

    def synthesize(self, text: str, destination: Path, *, voice: str, rate: float) -> None:
        try:
            import pyttsx3
        except ImportError as exc:
            raise TTSUnavailable("未安装 pyttsx3") from exc
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", int(175 * max(0.5, min(2.0, rate))))
            engine.save_to_file(text, str(destination))
            engine.runAndWait()
        except Exception as exc:
            raise TTSUnavailable(f"pyttsx3 合成失败: {exc}") from exc
        if not destination.exists():
            raise TTSUnavailable("pyttsx3 未生成音频文件")


class NullTTS:
    name = "none"

    def available(self) -> tuple[bool, str]:
        return False, "语音合成已禁用"

    def synthesize(self, text: str, destination: Path, *, voice: str, rate: float) -> None:
        raise TTSUnavailable("语音合成不可用")


class AudioService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.cache_dir = settings.data_dir / "audio"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.provider = self._select_provider()
        self.player, self.player_status = self._select_player()

    def _select_provider(self) -> TTSProvider:
        configured = self.settings.audio.provider.lower()
        classes = {"flite": FliteTTS, "espeak": EspeakTTS, "pyttsx3": Pyttsx3TTS}
        if configured == "none" or not self.settings.audio.enabled:
            return NullTTS()
        if configured == "auto":
            for cls in (FliteTTS, EspeakTTS, Pyttsx3TTS):
                provider = cls()
                ok, _ = provider.available()
                if ok:
                    return provider
            return NullTTS()
        provider = classes.get(configured, NullTTS)()
        return provider

    def _select_player(self) -> tuple[str | None, str]:
        configured = self.settings.audio.player.lower()
        candidates = {
            "ffplay": ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error"],
            "aplay": ["aplay", "-q"],
            "paplay": ["paplay"],
            "afplay": ["afplay"],
        }
        if configured != "auto" and configured in candidates:
            if shutil.which(candidates[configured][0]):
                return configured, "ok"
            return None, f"未找到播放器 {configured}"
        for name, command in candidates.items():
            if shutil.which(command[0]):
                return name, "ok"
        return None, "未找到可用音频播放器"

    def status(self) -> dict:
        tts_ok, tts_reason = self.provider.available()
        return {
            "provider": self.provider.name,
            "provider_available": tts_ok,
            "provider_reason": tts_reason,
            "player": self.player or "(none)",
            "player_reason": self.player_status,
            "cache_dir": str(self.cache_dir),
        }

    def cache_key(self, text: str) -> str:
        raw = f"{text}|{self.provider.name}|{self.settings.audio.voice}|{self.settings.audio.rate:.3f}|wav|22050|mono"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get_audio(self, text: str, *, force: bool = False) -> Path:
        if not text.strip():
            raise TTSUnavailable("文本为空，无法合成")
        ok, reason = self.provider.available()
        if not ok:
            raise TTSUnavailable(reason)
        destination = self.cache_dir / f"{self.cache_key(text)}.wav"
        if destination.exists() and destination.stat().st_size > 1000 and not force:
            return destination
        self.provider.synthesize(
            text,
            destination,
            voice=self.settings.audio.voice,
            rate=self.settings.audio.rate,
        )
        return destination

    def play(self, path: Path) -> PlaybackResult:
        if self.player is None:
            return PlaybackResult(False, self.player_status)
        commands = {
            "ffplay": ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", str(path)],
            "aplay": ["aplay", "-q", str(path)],
            "paplay": ["paplay", str(path)],
            "afplay": ["afplay", str(path)],
        }
        try:
            result = subprocess.run(
                commands[self.player],
                capture_output=True,
                text=True,
                timeout=120,
                stdin=subprocess.DEVNULL,
            )
            if result.returncode != 0:
                message = (result.stderr or result.stdout).strip()[:200]
                return PlaybackResult(False, f"播放失败（{self.player}）: {message}")
            return PlaybackResult(True, "ok")
        except (OSError, subprocess.SubprocessError) as exc:
            return PlaybackResult(False, f"播放失败: {exc}")

    def speak(self, text: str) -> PlaybackResult:
        try:
            path = self.get_audio(text)
        except TTSUnavailable as exc:
            return PlaybackResult(False, str(exc))
        return self.play(path)
