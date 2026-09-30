# Web video-editor research

Evaluated for architecture reuse, not as a replacement for the Jianying media backend.

## OpenCut / OpenCut classic

- Source: https://github.com/OpenCut-app/OpenCut
- The current repository is being rewritten around a Rust core and advertises an
  editor API, plugin architecture, headless mode, and scripting/MCP surfaces.
- Useful idea: keep the timeline document and command layer independent from UI
  and agent actions.
- Decision: do not adopt its runtime. It is still being rewritten and its
  playback/export stack is not a drop-in replacement for GStreamer/GES.

## OpenChatCut

- Source: https://github.com/imrob-dev/OpenCut
- Useful ideas: immutable timeline state, shared EditorCore commands, proposal /
  approval flow, and a Remotion Player/WebGL preview layer.
- Decision: reuse the separation between timeline state, commands, preview, and
  agent tools; do not reuse its Electron/Remotion runtime for native media
  decoding.

## Remotion

- Docs: https://convert.remotion.dev/docs/timeline/render
- Useful idea: the same JSON timeline payload must drive both the interactive
  Player and server render, which is a good oracle for renderAt consistency.
- Decision: use only as a conceptual renderAt/oracle reference. Remotion is not
  the multi-track native playback backend for this project.

## React timeline components

- Example: https://github.com/Ektie/react-video-timeline-editor
- Useful idea: pure reducers for clip geometry, trim/split/move, undo, and
  serializable project documents.
- Limitation: the project explicitly leaves persistence, media hosting, and
  encoding to the host application.
- Decision: no dependency; current Jianying IR already supplies the timeline
  document and needs a real media backend instead.

## Browser-native WebCodecs/WebGPU projects

- Example: https://github.com/afatabe/openreel
- Useful idea: hardware-oriented browser preview and local-first media flow.
- Limitation: browser capability and codec support remain deployment-dependent,
  which is the failure mode observed in the current previewer.
- Decision: keep browser rendering as a diagnostic/fallback concept only; the
  primary backend evaluation remains GStreamer/GES.
