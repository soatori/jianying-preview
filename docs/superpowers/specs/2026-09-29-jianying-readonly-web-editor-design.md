# Jianying 只读 Web 编辑器设计

**Status:** Approved architecture for implementation planning

## Goal

重建现有剪映预览器的浏览器播放与界面层，形成一个 OpenCut/Elah 思路的本地只读 Web 编辑器：Python 继续负责剪映草稿读取、解密、缓存和媒体服务；Node.js/TypeScript 负责 React 前端、时间线状态和播放内核。

首版只读：用户可以打开草稿、切换时间线、播放、暂停、跳转、查看轨道和属性，但原始剪映草稿永不写回。

## Architecture

```text
Python aiohttp service
  ├─ draft discovery / decryption / cache
  ├─ normalized editor-project API
  ├─ media / font endpoints
  └─ SSE draft-change events

Node.js + TypeScript + Vite frontend
  ├─ React shell and read-only panels
  ├─ framework-independent EditorCore
  ├─ microsecond PlaybackClock
  ├─ pure resolveScene(tUs, project)
  └─ DOM stage renderer
```

OpenCut and Elah are architectural references only. No Rust, WASM, OpenCut source, or external editor runtime is introduced.

## Data contract

Python exposes `GET /api/editor-project?draft=<did|path>&timeline=<timeline_id>` and returns `jypreview/editor-project@1`.

The document contains:

- `read_only: true`;
- draft identity, layout, source SHA-256, and timeline identity;
- canvas, FPS, and integer-microsecond duration;
- tracks with stable IDs, type, order, visibility, mute state, and render order;
- clips with target/source ranges, speed, reverse, visibility, media, transforms, text, styles, labels, and warnings;
- assets with served URLs and missing-media status.

All time ranges are integer microseconds and half-open. The frontend never receives a write capability.

## Playback and rendering

`PlaybackClock` is the only time authority. Media elements observe resolved scenes and never update the clock. `resolveScene(tUs, project)` is pure and deterministic. The initial renderer uses stable DOM layers: `<video>`, `<audio>`, `<img>`, and HTML/CSS text. A renderer interface is kept for a future Canvas/WebGL implementation.

## Safety and acceptance

- legacy-single, multi-timeline, hybrid, and encrypted readable drafts remain supported through the existing Python path;
- source draft files, `Timelines/`, and metadata are never written;
- only `.jypreview` or user-cache files may be added;
- unsupported masks, LUTs, curves, beauty effects, and advanced composites become explicit warnings/placeholders;
- browser scene layer IDs must match Python `/api/frame` samples;
- source SHA-256, mtime, and file lists must remain unchanged after UI use.
