"""Poll opened drafts for changes and push SSE reload events.

``os.stat`` only: no psutil, no ReadDirectoryChangesW. JianYing rewrites the whole
content file, so a signature change is the cheapest reliable signal.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path


class Watcher:
    def __init__(self, config, hub, session):
        self.config = config
        self.hub = hub
        self.session = session
        self.poll_ms = int(getattr(config, "watcher_poll_ms", 500))
        self._task: asyncio.Task | None = None
        self._signatures: dict[str, str] = {}
        self.watching: dict[str, Path] = {}
        self.last_poll = 0.0
        self.polls = 0

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    def watch(self, did: str, root: Path) -> None:
        self.watching[did] = Path(root)
        self._signatures.setdefault(did, self._signature(Path(root)))

    async def _loop(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(self.poll_ms / 1000)
            self.polls += 1
            self.last_poll = time.time()
            for did, root in list(self.watching.items()):
                try:
                    signature = await loop.run_in_executor(None, self._signature, root)
                except Exception:
                    continue
                previous = self._signatures.get(did)
                if previous is None:
                    self._signatures[did] = signature
                    continue
                if signature == previous:
                    continue
                self._signatures[did] = signature
                try:
                    view = await loop.run_in_executor(None, lambda: self.session.view(str(root), force=True))
                    self.hub.publish("draft.changed", {
                        "did": did, "path": str(root), "timelines":
                        [{"id": item.get("id"), "duration_us": item.get("duration_us")}
                         for item in view.timelines],
                        "source_sha256": next((replica.get("sha256") for item in view.timelines
                                               for replica in item.get("replicas", [])
                                               if replica.get("primary")), None)})
                except Exception as exc:
                    self.hub.publish("draft.error", {"did": did, "error": f"{exc.__class__.__name__}: {exc}"})

    def _signature(self, root: Path) -> str:
        return self.session.manager.probe_signature(root, None)
