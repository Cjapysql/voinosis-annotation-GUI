"""
재생 동기화 컨트롤러.

대시보드 마이크 오디오(QMediaPlayer)를 "마스터 시계"로 삼고, 그 재생 위치가
바뀔 때마다(positionChanged) 절대시각으로 환산해서 6개 카메라 스트림의
해당 프레임을 가져와 화면을 갱신한다. (PDF 요구사항: "영상 재생 시, 반드시
음성도 함께 나와야 함")

오디오가 없는 트라이얼(마이크 파일 누락 등)을 대비해, 오디오 없이도
QTimer 기반으로 동작하는 폴백 모드를 지원한다.
"""
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal, QTimer, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from front.stream_player import StreamPlayer


class PlaybackController(QObject):
    time_changed = Signal(float)     # 현재 절대시각 (unix time, float)
    playback_state_changed = Signal(bool)  # True=재생 중

    def __init__(self, total_start_ts: float, total_end_ts: float, parent=None):
        super().__init__(parent)
        self.total_start_ts = total_start_ts
        self.total_end_ts = total_end_ts

        self.stream_players: dict[str, StreamPlayer] = {}   # key: "driver_rgb" 등
        self.frame_callbacks: dict[str, Callable] = {}       # key -> update 콜백(프레임 받는 함수)

        self._audio_player: Optional[QMediaPlayer] = None
        self._audio_output: Optional[QAudioOutput] = None
        self._audio_base_abs_ts: float = total_start_ts   # 오디오 0ms 지점의 절대시각

        # 오디오 없을 때 쓰는 폴백 타이머 클럭
        self._fallback_timer = QTimer(self)
        self._fallback_timer.setInterval(33)  # 약 30fps
        self._fallback_timer.timeout.connect(self._on_fallback_tick)
        self._fallback_current_ts = total_start_ts
        self._is_playing = False

    # ------------------------------------------------------------------
    def register_stream(self, key: str, stream_player: StreamPlayer, on_frame: Callable):
        """key 예: 'driver_rgb', 'behavior_infrared' 등. on_frame(frame_ndarray_or_None)"""
        self.stream_players[key] = stream_player
        self.frame_callbacks[key] = on_frame

    def set_audio(self, wav_path: Path, base_abs_ts: float):
        """base_abs_ts: 이 wav 파일의 0ms 지점에 해당하는 절대 unix time."""
        self._audio_base_abs_ts = base_abs_ts
        self._audio_output = QAudioOutput()
        self._audio_player = QMediaPlayer()
        self._audio_player.setAudioOutput(self._audio_output)
        self._audio_player.setSource(QUrl.fromLocalFile(str(wav_path)))
        self._audio_player.positionChanged.connect(self._on_audio_position_changed)

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    # ------------------------------------------------------------------
    def play(self):
        self._is_playing = True
        self.playback_state_changed.emit(True)
        if self._audio_player is not None:
            self._audio_player.play()
        else:
            self._fallback_timer.start()

    def pause(self):
        self._is_playing = False
        self.playback_state_changed.emit(False)
        if self._audio_player is not None:
            self._audio_player.pause()
        else:
            self._fallback_timer.stop()

    def stop(self):
        self._is_playing = False
        self.playback_state_changed.emit(False)
        if self._audio_player is not None:
            self._audio_player.stop()
            self._audio_player.setPosition(0)
        else:
            self._fallback_timer.stop()
            self._fallback_current_ts = self.total_start_ts
        self.seek_to(self.total_start_ts)

    def seek_to(self, abs_ts: float):
        """타임라인 클릭 등으로 특정 절대시각으로 이동.

        오디오가 있을 때 화면 갱신을 QMediaPlayer의 positionChanged 신호에만
        맡기면, 요청한 시각이 오디오 커버 범위 밖이라 ms가 0으로 clamp되고
        마침 이미 위치가 0이면 Qt가 신호를 아예 안 쏴서 화면이 멈춘 것처럼
        보인다. 그래서 화면 갱신은 항상 여기서 요청받은 abs_ts 기준으로
        동기적으로 하고, 오디오 위치 갱신은 best-effort로 별도 요청한다.
        """
        abs_ts = max(self.total_start_ts, min(abs_ts, self.total_end_ts))
        if self._audio_player is not None:
            ms = int((abs_ts - self._audio_base_abs_ts) * 1000)
            ms = max(0, ms)
            self._audio_player.setPosition(ms)
        else:
            self._fallback_current_ts = abs_ts
        self._update_all_frames(abs_ts)
        self.time_changed.emit(abs_ts)

    # ------------------------------------------------------------------
    def _on_audio_position_changed(self, position_ms: int):
        abs_ts = self._audio_base_abs_ts + position_ms / 1000.0
        self._update_all_frames(abs_ts)
        self.time_changed.emit(abs_ts)

    def _on_fallback_tick(self):
        self._fallback_current_ts += self._fallback_timer.interval() / 1000.0
        if self._fallback_current_ts >= self.total_end_ts:
            self._fallback_current_ts = self.total_end_ts
            self.pause()
        self._update_all_frames(self._fallback_current_ts)
        self.time_changed.emit(self._fallback_current_ts)

    def _update_all_frames(self, abs_ts: float):
        for key, player in self.stream_players.items():
            frame = player.frame_at_time(abs_ts)
            self.frame_callbacks[key](frame)

    def release(self):
        for p in self.stream_players.values():
            p.release()
        if self._audio_player is not None:
            self._audio_player.stop()
