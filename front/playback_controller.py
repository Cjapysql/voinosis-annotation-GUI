"""
재생 동기화 컨트롤러.

대시보드 마이크 오디오(QMediaPlayer)를 "마스터 시계"로 삼고, 그 재생 위치를
기준으로 절대시각을 계산해 6개 카메라 스트림의 해당 프레임을 가져와 화면을
갱신한다. (PDF 요구사항: "영상 재생 시, 반드시 음성도 함께 나와야 함")

QMediaPlayer.positionChanged는 실측해보니 약 15Hz(64ms 간격)로만 갱신되기
때문에(백엔드 내부 폴링 주기, 조정 불가), 화면 갱신을 그 신호에 직접 묶으면
원본이 30fps여도 화면은 초당 15장 정도로만 바뀐다. 그래서 positionChanged는
"마지막으로 확인된 오디오 위치 + 그 시각의 벽시계 시각"만 기록하는 용도로
쓰고, 실제 화면 갱신은 별도의 빠른 QTimer(33ms, ~30fps)가 그 앵커 이후
흐른 실제 시간만큼 외삽(extrapolate)해서 계산한 절대시각으로 매 tick마다
갱신한다. 오디오 위치가 갱신될 때마다 앵커가 다시 맞춰지므로 드리프트도
누적되지 않는다.

오디오가 없는 트라이얼(마이크 파일 누락 등)을 대비해, 오디오 없이도
같은 디스플레이 타이머로 동작하는 폴백 모드를 지원한다.
"""
import time
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal, QTimer, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from front.stream_player import StreamPlayer


class PlaybackController(QObject):
    time_changed = Signal(float)     # 현재 절대시각 (unix time, float)
    playback_state_changed = Signal(bool)  # True=재생 중
    audio_ready = Signal()           # 오디오(있다면) 로딩이 처음 완료됐을 때 한 번 발생

    DISPLAY_INTERVAL_MS = 33  # 화면 갱신 주기 (~30fps)

    def __init__(self, total_start_ts: float, total_end_ts: float, parent=None):
        super().__init__(parent)
        self.total_start_ts = total_start_ts
        self.total_end_ts = total_end_ts

        self.stream_players: dict[str, StreamPlayer] = {}   # key: "driver_rgb" 등
        self.frame_callbacks: dict[str, Callable] = {}       # key -> update 콜백(프레임 받는 함수)

        self._audio_player: Optional[QMediaPlayer] = None
        self._audio_output: Optional[QAudioOutput] = None
        self._audio_base_abs_ts: float = total_start_ts   # 오디오 0ms 지점의 절대시각

        # 오디오 위치 앵커: 마지막으로 받은 (position_ms, 그 시각의 벽시계 monotonic 시각)
        self._audio_anchor_ms: float = 0.0
        self._audio_anchor_wall: float = time.monotonic()

        # 화면 갱신은 오디오 유무와 상관없이 항상 이 타이머가 담당 (30fps)
        self._display_timer = QTimer(self)
        self._display_timer.setInterval(self.DISPLAY_INTERVAL_MS)
        self._display_timer.timeout.connect(self._on_display_tick)

        self._fallback_current_ts = total_start_ts   # 오디오 없을 때 쓰는 폴백 클럭
        self._is_playing = False
        self._playback_rate = 1.0
        self._playback_limit_ts: float | None = None  # 설정되면 이 시각에서 자동 정지(구간 미리보기용)

    # ------------------------------------------------------------------
    def register_stream(self, key: str, stream_player: StreamPlayer, on_frame: Callable):
        """key 예: 'driver_rgb', 'behavior_infrared' 등. on_frame(frame_ndarray_or_None)"""
        self.stream_players[key] = stream_player
        self.frame_callbacks[key] = on_frame

    def set_playback_limit(self, end_ts: float | None):
        """이 시각에 도달하면 재생을 자동으로 멈춘다(구간 하나만 미리보기).
        None이면 평소처럼 total_end_ts(전체 트라이얼 끝)까지 재생."""
        self._playback_limit_ts = end_ts

    def set_audio(self, wav_path: Path, base_abs_ts: float):
        """base_abs_ts: 이 wav 파일의 0ms 지점에 해당하는 절대 unix time.
        재생 중 마이크를 바꾸는 경우처럼 다시 호출될 수 있으므로, 이전 오디오
        재생 중이었다면 먼저 멈추고 교체한다."""
        if self._audio_player is not None:
            self._audio_player.stop()
        self._audio_base_abs_ts = base_abs_ts
        self._audio_output = QAudioOutput()
        self._audio_player = QMediaPlayer()
        self._audio_player.setAudioOutput(self._audio_output)
        self._audio_player.setSource(QUrl.fromLocalFile(str(wav_path)))
        self._audio_player.setPlaybackRate(self._playback_rate)  # 마이크 전환 등으로 새 플레이어가 생겨도 기존 배속 유지
        self._audio_player.positionChanged.connect(self._on_audio_position_changed)
        self._audio_player.mediaStatusChanged.connect(self._on_audio_media_status_changed)

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    @property
    def is_audio_ready(self) -> bool:
        """오디오가 없으면(트라이얼에 마이크 파일이 없는 경우) 기다릴 것도 없이
        True. 있으면 실제로 로딩이 끝나 seek이 확실히 먹히는 상태인지."""
        if self._audio_player is None:
            return True
        return self._audio_player.mediaStatus() in (
            QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia
        )

    def set_playback_rate(self, rate: float):
        """재생 배속 변경 (0.5, 1.0, 1.5, 2.0 등). 속도가 바뀌는 순간 위치가
        튀지 않도록, 지금까지 경과한 만큼을 옛 배속 기준으로 먼저 앵커에
        반영한 뒤 벽시계 기준점을 새로 잡는다."""
        if self._audio_player is not None:
            elapsed_ms = (time.monotonic() - self._audio_anchor_wall) * 1000.0 * self._playback_rate
            self._audio_anchor_ms += elapsed_ms
        self._audio_anchor_wall = time.monotonic()
        self._playback_rate = rate
        if self._audio_player is not None:
            self._audio_player.setPlaybackRate(rate)

    # ------------------------------------------------------------------
    def play(self):
        self._is_playing = True
        self.playback_state_changed.emit(True)
        if self._audio_player is not None:
            self._audio_player.play()
            # 벽시계 기준점만 새로 잡고(마지막 seek 이후 play를 누르기까지 걸린
            # 시간만큼 외삽이 앞서 나가는 걸 막기 위함), ms 값은 건드리지 않는다.
            # QMediaPlayer.setPosition()은 비동기라 seek 직후 바로 play를 누르면
            # position()이 아직 이전 값(예: 0)을 돌려줄 수 있어서, 그걸로 다시
            # 앵커를 잡으면 seek_to()가 지정한 위치가 아니라 엉뚱한 데서(주로
            # 맨 처음부터) 재생이 시작되는 버그가 있었음 - _audio_anchor_ms는
            # seek_to()가 이미 정확히 기록해뒀으므로 그 값을 그대로 신뢰한다.
            self._audio_anchor_wall = time.monotonic()
        self._display_timer.start()

    def pause(self):
        self._is_playing = False
        self.playback_state_changed.emit(False)
        if self._audio_player is not None:
            self._audio_player.pause()
        self._display_timer.stop()

    def stop(self):
        self._is_playing = False
        self.playback_state_changed.emit(False)
        self._display_timer.stop()
        if self._audio_player is not None:
            self._audio_player.stop()
            self._audio_player.setPosition(0)
        else:
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
            self._audio_anchor_ms = ms
            self._audio_anchor_wall = time.monotonic()
        else:
            self._fallback_current_ts = abs_ts
        self._update_all_frames(abs_ts)
        self.time_changed.emit(abs_ts)

    # ------------------------------------------------------------------
    def _on_audio_media_status_changed(self, status):
        """QMediaPlayer.setPosition()은 미디어가 아직 로딩 중일 때 호출하면
        조용히 무시될 수 있다 (스티칭된 wav가 수백 MB라 로딩에 시간이 걸림) -
        페이지에 들어오자마자 seek_to()로 특정 태스크 위치로 이동시켜도 그 시점에
        로딩이 안 끝났으면 실제로는 반영이 안 된 채 넘어갈 수 있고, 이후 재생을
        누르면 실제 위치(0)를 보고하는 positionChanged가 들어와서 앵커가 다시
        맨 처음으로 돌아가 버렸었다. 로딩이 완료되는 시점에 우리가 기록해둔
        목표 위치(_audio_anchor_ms)를 다시 적용해서 확실히 반영시킨다."""
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            self._audio_player.setPosition(int(self._audio_anchor_ms))
            self.audio_ready.emit()

    def _on_audio_position_changed(self, position_ms: int):
        # 화면은 갱신 안 하고 다음 _on_display_tick이 외삽할 기준점만 갱신
        self._audio_anchor_ms = position_ms
        self._audio_anchor_wall = time.monotonic()

    def _on_display_tick(self):
        if self._audio_player is not None:
            elapsed_ms = (time.monotonic() - self._audio_anchor_wall) * 1000.0 * self._playback_rate
            estimated_ms = self._audio_anchor_ms + elapsed_ms
            abs_ts = self._audio_base_abs_ts + estimated_ms / 1000.0
        else:
            self._fallback_current_ts += self.DISPLAY_INTERVAL_MS / 1000.0 * self._playback_rate
            abs_ts = self._fallback_current_ts

        effective_end = self._playback_limit_ts if self._playback_limit_ts is not None else self.total_end_ts
        if abs_ts >= effective_end:
            if self._audio_player is not None:
                # 추정치(estimated_ms)는 오디오가 잠깐 멈칫(버퍼링 등)해도 벽시계만
                # 믿고 계속 흘러서, 아직 안 끝난 구간을 끝났다고 착각해 조기
                # 정지할 수 있다. 정지를 확정하기 전에 마지막으로 확인된 실제
                # 오디오 위치(_audio_anchor_ms, positionChanged로 갱신됨)가 진짜로
                # 한계에 도달했는지 다시 확인한다.
                real_abs_ts = self._audio_base_abs_ts + self._audio_anchor_ms / 1000.0
                if real_abs_ts < effective_end:
                    abs_ts = effective_end
                    self._update_all_frames(abs_ts)
                    self.time_changed.emit(abs_ts)
                    return
            abs_ts = effective_end
            self.pause()
        self._update_all_frames(abs_ts)
        self.time_changed.emit(abs_ts)

    def _update_all_frames(self, abs_ts: float):
        for key, player in self.stream_players.items():
            frame = player.frame_at_time(abs_ts)
            self.frame_callbacks[key](frame)

    def release(self):
        for p in self.stream_players.values():
            p.release()
        if self._audio_player is not None:
            self._audio_player.stop()
