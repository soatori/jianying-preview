# GStreamer/GES evaluation

Date: 2026-09-29

## Environment

- Python: 3.14 x64
- Isolated package: `gstreamer-bundle==1.28.0`
- Runtime libraries/plugins/tools: GStreamer 1.28.7
- GES: available through Python introspection
- Probe media: `<素材绝对路径>/<clip>.MP4`

## Results

- `GstGesBackend.open()` succeeded.
- `render_at()` returned RGBA frames for 0, 0.5, 3 and 5 seconds.
- Returned frame PTS matched requested timeline time in the probe.
- GES reverse property produced a distinct frame and is exposed by the backend.
- The full 64-second 该草稿 window profile opened with 105 normalized clips;
  samples at 0, 5, 30 and 60 seconds returned matching PTS after draining the
  appsink between random seeks.
- The isolated aiohttp service opened the full profile and passed native
  capabilities/open/render/play/pause/seek/close endpoint checks.  The
  multipart stream endpoint still closes before its first client-visible frame;
  this remains a cutover blocker.
- Backend `play/pause/snapshot/close` passed.
- Four-frame probe wall time was approximately 5.5 seconds including runtime
  startup; per-frame timing still needs a focused benchmark before claiming
  realtime playback.
- GStreamer emitted an optional `giolibproxy.dll` module warning from the
  isolated wheel; media decode and GES rendering still succeeded.

## Web project findings

- OpenCut/OpenChatCut: useful immutable timeline + command/editor-core
  separation, but not a drop-in decoder backend.
- Remotion: useful same-JSON interactive Player/server-render oracle pattern;
  not a native multitrack decoder.
- React timeline editor projects: useful pure clip geometry reducers, but leave
  media hosting/encoding to the host.
- WebCodecs/WebGPU projects: useful browser acceleration ideas, but still have
  browser codec/runtime variability.

## Decision

GStreamer/GES is viable for the native backend evaluation. The IR adapter and
server capabilities/control/exact-frame surfaces are implemented. Do not switch
the browser UI to the native backend until multipart/continuous transport,
text/effect composition, audio output and performance audit are complete.
