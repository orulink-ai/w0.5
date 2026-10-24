# Camera preview and face tracking

The local cascade feature uses `robot-console.cascade.example.json`: SenseVoice INT8 → Ollama Qwen3 4B → Chinese VITS, with required workbench/Pi/persistent memory services, transcript and latency telemetry. Both face-gated modes and volume 80 are preserved. Prepare models using the adjacent vi-agent's `packages/vi-agent/scripts/setup-local-cascade.ps1`, run this folder's `setup.ps1`, copy the cascade config to `runtime/robot-console/config.json`, then Start. See vi-agent `packages/vi-agent/docs/local-cascade-deployment.zh-CN.md`. The native LLaMA-Omni2 limitations described below apply only to that separate pipeline. Firmware must actually acknowledge volume 80.

[中文](README.md) · [Firmware and wiring](../../firmware/esp32/examples/imx708_usb/README.en.md) · [Technical notes](../../docs/camera-imx708.en.md)

Status: runnable hardware debugging version. Image quality, autofocus and sustained frame rate remain unaccepted. YuNet detects faces and ByteTrack associates temporary IDs across frames. This does not recognize identities or command robot motors.

## Windows setup

### Optional mouth assistance (local-cascade)

Run `pwsh -File setup-mouth.ps1`, set `cameraPython` in private `runtime/robot-console/config.json` to `.venv-mouth/Scripts/python.exe`, then restart the console. This prepares an isolated Python 3.12 environment with locked MediaPipe 1.1.1 dependencies and a SHA256-verified official float16 v1 Face Landmarker model (~3.76MB). The existing camera environment and firmware are unchanged; volume remains 80. Enable the experimental mouth checkbox in the web console; it defaults off and persists as `mouth_assist` in ignored view settings. `configure.mouthAssist` accepts booleans; status is returned as `voice.mouth`.

The latest-frame worker runs at roughly 10 FPS on the host CPU. It locks one temporary face track and gates sound-only starts while a visible mouth is stationary. Stationary pre-speech frames calibrate background levels; calibration freezes during speech, with a lower continuation threshold for quiet syllables. Assisted submission requires audio quiet and stationary lips together for 600ms; continuing audio or mouth motion keeps listening. Missing/stale (>500ms) visual evidence or model failures require both visual unavailability and audio silence for 1000ms before fallback. With assistance disabled, audio silence still ends at 450ms. Changing this option cancels the old session. All faces absent for two seconds, reconnects and rotations clear the target; a lost target does not automatically switch to a bystander. Only bounded metadata reaches Node stdin, without face images or landmarks. This is geometric motion assistance, not semantic turn completion, lip reading, speaker classification or ASR denoising. Pauses beyond 600ms, smiles, chewing, yawns, occlusion and poor lighting can affect it; noisy-event acceptance remains pending.

Local-cascade microphone capture no longer submits on a duration cap. While listening, SenseVoice recognizes 12-second windows with 500ms overlap, then approximately every 11.5 seconds; draining audio never resets endpoint evidence. After a true endpoint, the remaining window is recognized and merged with previous text before one LLM call. This is incremental chunked offline ASR, not a native streaming model. Each ASR request remains bounded to 15 seconds; a backlog exceeding three unfinished chunks, a 30-second request timeout, recognition errors, cancellation or text exceeding the existing 16000-character workbench bound stops the turn explicitly without a partial reply. Qwen still uses an 8192-token context, so arbitrarily long content cannot be promised to fit. The console exposes the endpoint reason and reports post-endpoint ASR drain time. The native LLaMA-Omni2 path described below retains its own 15-second limit.

The preview now draws a lip outline and corner markers, with an in-video status badge: green for motion, cyan for stationary lips, and amber while waiting/unavailable. Stationary does not mean closed or finished speaking. Detection thresholds and endpoint behavior are unchanged. Geometry follows mirroring/rotation and disappears after 250ms, target loss or a frame-size change; it stays in local preview memory and is not published as metadata. Narrow previews are 240px tall. To inspect lips alone, leave automatic conversation off and enable mouth assistance; no microphone is needed.

### Voice preparation and optional prelistening (local-cascade)

In both modes, 0.75 seconds of confirmed face absence stops new turns. Unsubmitted capture is discarded; an already submitted turn finishes recognition, generation and speaker drain before parking. Conversations stay enabled and stable reentry rearms automatically, including single mode when departure occurred during its reply. Completion retains a 1.5-second cooldown followed by fresh face confirmation. With prelistening enabled, the next standby process resumes the bounded local buffer without ASR before face confirmation. Playback and process handoff still pause capture. Video stale for one second uses the same finish policy, so a later video delay cannot escalate departure into forced cancellation. Manual stop, actual audio transport loss, camera worker exit and configuration changes still cancel immediately. This finish-on-departure policy applies only to local-cascade; the native path below retains cancellation.

Device stdout emits metadata-only `voice-lifecycle` JSON for finish requests, cancellation, speaker drain and session exit, with reason, phase, turn ID and timestamp. Use launcher Logs to inspect it; transcripts, reply text, PCM and credentials are excluded.

Enabling face conversations prepares one standby Node/Python voice process and the shared audio connection while video is fresh. Face confirmation adopts it; continuous turns reuse it, and a completed encounter prepares a new standby process. Single mode still needs departure/reentry. By default the microphone stays off until face confirmation.

Optional prelistening retains at most 1.5 seconds in RAM, with no ASR before face confirmation. Only fresh frames since the current face first appeared can be replayed. Stop, camera loss, or configuration changes dispose of standby capture and its buffer. The console explicitly shows buffered input as not sent to recognition. Continuous UART audio can reduce idle video to approximately 14 FPS. SenseVoice remains utterance-based.

Firmware input gain is 30dB; the web console provides an additional protected 0–12dB host gain, default 0, applied before VAD/ASR. It does not remove noise or improve SNR. Logarithmic metering shows raw/processed RMS, effective gain and the trigger threshold; output volume remains 80. Strict HTTP options `configure.prelisten` (boolean) and `configure.inputGainDb` (integer 0–12) persist in ignored view settings and cancel the old session when changed. Input telemetry expires after 500ms.

### Base camera environment

Install Python 3.12 with Tk and the CH343 driver. Use a USB data cable. Find the actual port in Device Manager; COM15 is only the development default.

```powershell
cd tools/camera_facetrack
powershell -ExecutionPolicy Bypass -File setup.ps1
New-Item -ItemType Directory runtime/robot-console -Force
Copy-Item robot-console.example.json runtime/robot-console/config.json
pwsh -File robot-console.ps1 -Action Start -OpenBrowser
```

The unified entry opens one web console at `http://127.0.0.1:5173`; the camera process runs with `--headless`, without a second Tk window. The default `VI_NATIVE_ONLY=true` web mode mounts board controls and real replies only, without cloud voice, workbench polling, text input or key settings. The script supports Windows PowerShell 5.1 and PowerShell 7. Omit `-OpenBrowser` to avoid opening another system browser tab. Setup downloads YuNet from OpenCV Zoo into the ignored `models/` directory.

First prepare the adjacent vi-agent checkout, Node.js dependencies, local LLaMA-Omni2 weights, CUDA Python environment and Matcha/Whisper sources. The launcher does not install prerequisites or flash firmware. The default uses only the native speech-to-speech model: no API keys, extra text model or cloud ASR/TTS are needed, and failures do not fall back to cloud speech.

JSON paths are relative to the launcher directory; absolute paths also work. `modelRoot` contains LLaMA-Omni2 source and `models/`, while `modelPython` points to its environment. Edit ignored `runtime/robot-console/config.json`, or supply `-Config path`; otherwise the example is used. JSON stores paths, COM port, features and ports, never credentials. `features.camera` and `faceVoice` default to true; faceVoice requires camera. `workbench` defaults to false, so Pi and a separate text model are not started. Explicitly enabling the optional workbench does not make its startup failure stop native speech or camera.

```powershell
pwsh -File robot-console.ps1 -Action Status
pwsh -File robot-console.ps1 -Action Logs -Tail 40
pwsh -File robot-console.ps1 -Action Restart
pwsh -File robot-console.ps1 -Action Stop
```

Default ports are native model 8790, device 8791 and web 5173; optional workbench API 8787 is disabled by default. Configure distinct ports in JSON. Healthy existing listeners are reused as external/unmanaged and never stopped or taken over. Owned processes are identified by PID, creation time, executable and exact command before their trees are stopped. Model readiness has a 180-second limit, adjustable with `-ModelTimeoutSeconds`, with progress every ten seconds. Logs and process metadata stay in ignored runtime. An incompatible listener causes an error instead of a port switch or killing another program. Logs tails at most eight launcher log files and never reads `.env`. Service health alone does not verify board acoustics.

For development, `.venv\Scripts\python.exe app.py --watch --autostart --source serial://COM15`, `start-dev.cmd` and `start.cmd` retain the light Tk debugging interface. Do not open another serial owner alongside the unified launcher. Use `--source 0` for a PC webcam. Hot reload restarts the application and reconnects the device.

Left/right rotation, reset and mirroring affect the image only. The top counter measures displayed FPS. The footer reports native dimensions, processing FPS, inference time and time after frame reception. The latter excludes acquisition and transmission and is not an end-to-end latency measurement.

## Face-triggered speech (experimental)

Use v19 firmware with the audio component and a separate adjacent `vi-agent` checkout with Node.js dependencies installed. Start its local LLaMA-Omni2 service at `http://127.0.0.1:8790`; see that project's `packages/vi-agent/docs/voice-workbench.zh-CN.md` for model setup. Set `WTCC_VI_AGENT_ROOT` if the checkout is elsewhere.

The launcher enables face speech when configured; standalone Tk starts with speech disabled. A fresh face must remain visible for one second before the microphone opens, including manual listen requests. Default minimum RMS is 250 with a noise floor of 50; after speech, 800 ms silence submits audio. Capture is limited to 15 seconds. Camera preview and tracking continue throughout.

| Mode | Behavior |
| --- | --- |
| `continuous` (default) | The same Node process returns directly to listening after playback. Face absence for 0.75 seconds or video stale for one second cancels capture, generation or playback at any stage. |
| `single` | A face triggers one `--once` turn. Completion blocks re-triggering until the person leaves and appears again. |

The selected mode persists as `voice_mode` in ignored `runtime/view-settings.json`. HTTP `configure.mode` accepts only `single` or `continuous`; other values are rejected. Changing modes cancels the old active session. A missing face cannot open the microphone. Acoustic and sustained-session acceptance remain pending.

v19 uses a 400 ms software playback queue with a 200 ms prefill. A single UART broker shares video and audio at 4 Mbaud. During microphone capture or speaker playback, v19 targets 1Mbps / 14FPS video, returning to 2.4Mbps / 28FPS when idle; displayed FPS depends on transport and decoding. Only the microphone pauses during reply generation and playback; interruption during playback is not supported. `voice_session.py` launches vi-agent's real `board-omni-main.ts --json-events` (adding `--once` for single mode) and supplies an authenticated loopback TCP broker connection instead of opening the serial port again. Only loopback HTTP model endpoints are accepted. Native audio turns are independent and currently do not invoke Pi tools or workbench memory. Model weights, recordings and credentials stay outside this repository. A model startup error leaves camera preview running.

The GUI starts `http://127.0.0.1:8791` for `/api/robot/status`, `/api/robot/camera.mjpeg` and `/api/robot/control`. The unified web entry is vi-agent's `http://127.0.0.1:5173`. Port 8790 remains the model service; the audio TCP broker uses a separate temporary port.

Validation scope: an earlier manual Chinese voice turn through this console completed on the board and the user confirmed the reply. Separate playback was confirmed clear at volume 80. v19 has been flashed and face-triggered turns have completed with continuous preview, including one with 1.68 seconds captured and 5.64 seconds played. A persistent same-Node session was tested over multiple turns. The actual third-turn error was a 12-second no-speech timeout: 607 microphone packets arrived with zero sequence gaps and zero transport errors, so this was not a bridge disconnection. First-cause error preservation is fixed. Quiet listening is being changed to continue while packets arrive, with missing audio packets treated as fatal; physical regression remains pending. The session watchdog has been extended to 45 seconds with heartbeats, with seven related regressions passing. Current model time to first audio is about 6–13 seconds, and audio quality and conversational fluency remain unaccepted. Offline regression passed 68 camera-side and 20 TypeScript cases, plus 7 additional first-cause and session-heartbeat regressions; these do not establish physical stability or acoustic acceptance.

The speaker test uses the prompt “请用中文简短介绍一下你自己。” to generate a Chinese reply, rather than a fixed greeting or literal announcement. It does not open the microphone or enable automatic conversation. `transport_stats` retains metadata for the eight most recent audio control errors. Only an explicit `invalid_pcm` rejection allows the same sequence to be resent, with at most three transmission attempts (the initial attempt plus two retries). ACK timeouts are not retried, avoiding duplicate playback. The first bridge/model error is preserved if later cleanup also fails.

## Debugging and tests

Stop preview and close other serial monitors before opening these exclusive-port diagnostics:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe tools/check_usb.py --port COM15 --seconds 25
.venv\Scripts\python.exe tools/calibrate_focus.py --port COM15
```

The USB check reports accepted frames, CRC failures, sequence gaps, data rate and maximum arrival gap; it does not assess optical quality. The experimental focus tool requires a stationary, visible face under suitable lighting. It refuses background calibration when no face is detected and restores autofocus on failure. It writes local diagnostic images and reports to `runtime/`; do not commit those files.

`runtime/`, `.venv/` and downloaded model weights are ignored. Legacy HTTP decoder tests require FFmpeg on PATH or are skipped. USB decoding uses PyAV and needs no separate FFmpeg executable. Provisioning and HTTP modules retain regression coverage, but the current GUI exposes no provisioning button and the firmware does not start Wi-Fi.

For a manual Python setup (including non-Windows environments): create a Python 3.12 virtual environment, install `requirements.txt` with pip, then run `python face_engine.py` before starting `python app.py --source 0`. Windows USB hardware is the validated target.

## Source map

| File | Responsibility |
| --- | --- |
| `app.py` | Tk UI, workers, rotation, counters, hot reload and reconnect |
| `robot-console.ps1` / `robot-console.example.json` | Unified web startup, path/features configuration, service health and owned process lifecycle |
| `serial_video.py` / `board_broker.py` | Single serial owner, video decoding, microphone/ACK demultiplexing and local audio broker |
| `robot_console_server.py` | Loopback HTTP status, preview and control |
| `face_engine.py` | YuNet, ByteTrack and annotations |
| `mouth_tracking.py` / `setup-mouth.ps1` | Optional lip motion, target lock, verified model download and isolated environment |
| `face_gate.py` / `voice_panel.py` | Face debounce, speech controls and session state |
| `voice_session.py` | vi-agent persistent speech process, events and bounded cancellation |
| `camera_setup.py` / `video_source.py` | Retained provisioning / HTTP modules, unused by the current USB path |
| `tools/` / `tests/` | Bounded diagnostics and offline regression tests |

The default is 4,000,000 baud. For older 2 Mbaud firmware set `$env:WTCC_SERIAL_BAUD='2000000'`. Both endpoints must agree. Do not open a serial monitor or flasher while preview owns the port.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Model weights, scene photos, Wi-Fi credentials, flash backups and compiled binaries are excluded from this migration.
