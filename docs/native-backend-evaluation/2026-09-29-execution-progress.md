# Execution progress

- Environment ruling: current worktree already contains the previous playback
  refactor as uncommitted user work on `master`; do not reset or create a clean
  replacement checkout.
- Task 1 complete: isolated `gstreamer-bundle==1.28.0` installed and GES
  probe passed on real <clip>.MP4 (0/0.5/3/5s exact PTS, reverse, pause,
  snapshot, close).
- Task 2 complete: `GstGesBackend` and FrameDescriptor path adapter are
  implemented; normalized video/audio clip profiles, reverse, speed effects,
  random seeks, and a full 64-second/105-clip 该草稿 profile render in the
  isolated GStreamer Python.
- Task 3 in progress: optional server capability/open/render/snapshot/close
  plus play/pause/seek and multipart frame-stream endpoints are wired, but the
  browser UI has not been switched because native text/effect composition and
  end-to-end audio/continuous transport still need acceptance.
- Task 3 evidence: a GStreamer-enabled isolated server opened the full
  105-clip 该草稿 profile and returned a 881KB PNG from native render; play,
  pause, seek, snapshot and close endpoints returned success. Multipart stream
  transport was fixed by serializing GES calls and correcting multipart bytes;
  the main server now returns PNG stream frames.
- Task 4 complete: default page mode now opens GStreamer/GES, hides browser
  media elements, displays the native stream, syncs the master clock through
  `/api/backend/snapshot`, and uses native play/pause/seek/renderAt.
- Ruling: keep `?backend=browser` as an explicit diagnostic mode while native
  acceptance continues; the default is now GStreamer/GES and the old browser
  kernel is no longer the normal playback path.
- Ruling: keep browser UI kernel during migration because full IR conversion,
  GES speed effects, text/effect composition, and browser frame/audio transport
  are not yet acceptance-complete. Removing it now would create an unverified
  playback gap.
