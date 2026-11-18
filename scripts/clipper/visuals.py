"""Visual Inspector for New Game Showcases (`visuals.py`).

Uses OpenCV on sampled frames of each candidate clip to measure:
1. `environment_score`: Wide-scene richness, outdoor lighting, color diversity, and spatial depth
   (heavily penalizing dark indoor corners/shacks, pause menus, or loading screens).
2. `graphics_score`: High-frequency Laplacian texture detail, contrast, and HSV vibrancy.
3. `action_score`: Gameplay and character movement across frames.
4. `streamer_score`: Facecam liveness.
"""

import numpy as np


def evaluate_clip_visuals(video_path, t0, t1, info, analysis=None):
    try:
        import cv2
    except ImportError:
        return {
            "visual_score": 80.0, "environment_score": 75.0,
            "graphics_score": 75.0, "action_score": 70.0,
            "streamer_score": 70.0, "cam_alive": True,
        }

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return {
            "visual_score": 80.0, "environment_score": 75.0,
            "graphics_score": 75.0, "action_score": 70.0,
            "streamer_score": 70.0, "cam_alive": True,
        }

    dur = max(1.0, t1 - t0)
    step = max(0.5, dur / 32.0)
    t = t0
    prev_gray = None
    motion_per_step = []
    brightness_vals = []
    saturation_vals = []
    sharpness_vals = []
    color_spread_vals = []

    try:
        while t < t1:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            small = cv2.resize(frame, (480, 270))
            hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

            brightness_vals.append(float(hsv[:, :, 2].mean()))
            saturation_vals.append(float(hsv[:, :, 1].mean()))
            # Hue std measures how diverse/rich the environment colors are (city lights, sky, foliage vs brown shack wall)
            color_spread_vals.append(float(hsv[:, :, 0].std()))
            sharpness_vals.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))

            if prev_gray is not None:
                diff = np.abs(gray.astype(np.float32) - prev_gray.astype(np.float32))
                motion_per_step.append(float(diff.mean()))
            prev_gray = gray
            t += step
    finally:
        cap.release()

    if not brightness_vals:
        return {
            "visual_score": 75.0, "environment_score": 70.0,
            "graphics_score": 70.0, "action_score": 65.0,
            "streamer_score": 65.0, "cam_alive": True,
        }

    avg_bright = float(np.mean(brightness_vals))
    avg_sat = float(np.mean(saturation_vals))
    avg_sharp = float(np.mean(sharpness_vals))
    avg_color_spread = float(np.mean(color_spread_vals))
    avg_motion = float(np.mean(motion_per_step)) if motion_per_step else 5.0

    # 1. Environment & World Openness Score (penalizes dark cramped rooms where avg_bright < 50)
    bright_norm = min(100.0, max(5.0, (avg_bright - 30.0) * 1.45))
    color_norm = min(100.0, avg_color_spread * 2.2)
    environment_score = round(0.55 * bright_norm + 0.45 * color_norm, 1)

    # 2. Graphics & Detail Score (texture sharpness + lighting contrast + color saturation)
    sharp_norm = min(100.0, avg_sharp / 7.5)
    sat_norm = min(100.0, avg_sat * 1.25)
    graphics_score = round(0.50 * sharp_norm + 0.30 * sat_norm + 0.20 * bright_norm, 1)

    # 3. Character & Gameplay Action Score
    action_score = round(min(100.0, avg_motion * 6.5), 1)

    # 4. Streamer Facecam Liveness
    cam_alive = True
    streamer_score = 70.0
    if analysis and len(analysis) == 4:
        faces, times, grays, scale = analysis
        if len(grays) >= 6 and faces:
            fx = int(np.median([f[1] for f in faces]) * scale)
            fy = int(np.median([f[2] for f in faces]) * scale)
            fw = int(np.median([f[3] for f in faces]) * scale)
            fh = int(np.median([f[4] for f in faces]) * scale)
            stack = np.stack([g.astype(np.float32) for g in grays])
            patch = stack[:, max(0, fy):fy + max(1, fh), max(0, fx):fx + max(1, fw)]
            if patch.size and len(patch) >= 2:
                frame_diffs = np.abs(np.diff(patch, axis=0)).mean()
                streamer_score = round(min(100.0, frame_diffs * 18.0), 1)
                if frame_diffs < 2.0:
                    cam_alive = False

    dark_shack_penalty = 25.0 if avg_bright < 42.0 else 0.0
    deadpan_penalty = 20.0 if not cam_alive else 0.0
    visual_score = round(
        max(
            10.0,
            0.35 * environment_score
            + 0.30 * graphics_score
            + 0.20 * action_score
            + 0.15 * streamer_score
            - dark_shack_penalty
            - deadpan_penalty,
        ),
        1,
    )
    return {
        "visual_score": visual_score,
        "environment_score": environment_score,
        "graphics_score": graphics_score,
        "action_score": action_score,
        "streamer_score": streamer_score,
        "cam_alive": cam_alive,
    }
