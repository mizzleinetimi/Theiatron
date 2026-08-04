"""Video feed with frame skipping and looping.

All clips are normalized by scripts/get_videos.sh to the same fps, so every
feed advances in lockstep: one processed frame per engine tick of
`1 / process_fps` seconds of video time.
"""

from __future__ import annotations

import cv2


class VideoFeed:
    def __init__(self, path: str, process_fps: float = 10.0, loop: bool = True):
        self.path = path
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            raise FileNotFoundError(f"cannot open video: {path}")
        self.native_fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.skip = max(1, round(self.native_fps / process_fps))
        # Video-time seconds between processed frames.
        self.dt = self.skip / self.native_fps
        self.loop = loop
        self.loops = 0

    def read(self):
        """Return (frame, wrapped). frame is None when ended and loop=False.

        wrapped=True on the first frame after a loop restart — caller must
        reset its tracker and arrival extractor.
        """
        wrapped = False
        for _ in range(self.skip - 1):
            self.cap.grab()
        ok, frame = self.cap.read()
        if not ok:
            if not self.loop:
                return None, False
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self.loops += 1
            wrapped = True
            for _ in range(self.skip - 1):
                self.cap.grab()
            ok, frame = self.cap.read()
            if not ok:
                return None, False
        return frame, wrapped

    def release(self) -> None:
        self.cap.release()
