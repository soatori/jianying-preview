"""Registry ownership ordering without requiring a native sink."""

import asyncio
import threading
from contextlib import AsyncExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from jypreview.config import Config
from jypreview.mlt_backend import CompiledTimeline, MltCompiler, PlaybackController
from jypreview.model.timeline import TimelineModel
from jypreview.server import handlers_backend
from jypreview.server.app import create_app


async def queued_close_cancellation():
    """Exercise real handle/executor teardown while close is behind a busy call."""
    for action in ("replacement", "explicit close"):
        started, release = threading.Event(), threading.Event()
        owners = []

        class Controller:
            def __init__(self):
                self.closed = False
                self.fail_close = False
                owners.append(self)

            def busy(self):
                started.set()
                assert release.wait(5), "busy executor was never released"

            def close(self):
                if self.fail_close:
                    self.fail_close = False
                    raise RuntimeError("uncertain teardown")
                self.closed = True

            def open(self, model):
                assert all(owner.closed for owner in owners if owner is not self), "probe before old close"
                return {"playback_id": "next"}

        view = SimpleNamespace(did="draft", resolve_timeline=lambda selector: {"id": selector},
                               timeline_model=lambda tid: None)
        unrelated = SimpleNamespace(playback_id="unrelated")
        app = {"session": SimpleNamespace(view=lambda selector: view),
               "playback_lifecycle_lock": asyncio.Lock(), "playback_backends": {"other:timeline": unrelated}}
        with patch.object(handlers_backend, "PlaybackController", Controller):
            handle = handlers_backend.PlaybackHandle()
            handle.playback_id = "old"
            app["playback_backends"]["draft:timeline"] = handle
            request = SimpleNamespace(app=app, query={"draft": "draft", "timeline": "timeline", "playback_id": "old"})
            busy = asyncio.create_task(handle.call("busy"))
            assert await asyncio.to_thread(started.wait, 5)
            handler = handlers_backend.open_backend if action == "replacement" else handlers_backend.close_backend
            closing = asyncio.create_task(handler(request))
            while handle.executor._work_queue.qsize() == 0:
                await asyncio.sleep(0.001)
            timer = threading.Timer(0.05, release.set)
            timer.start()
            closing.cancel()
            await asyncio.sleep(0.005)
            assert app["playback_lifecycle_lock"].locked() and not closing.done()
            assert not handle.controller.closed
            closing.cancel()  # repeated cancellation must not discard the shielded native future
            try:
                await closing
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("canceled teardown must propagate cancellation")
            finally:
                release.set()
                timer.join()
            await busy
            assert handle.controller.closed, f"{action}: queued native close was canceled"
            assert not app["playback_lifecycle_lock"].locked()
            assert app["playback_backends"] == {"other:timeline": unrelated}
            assert (await handlers_backend.open_backend(request)).status == 200
            next_handle = app["playback_backends"]["draft:timeline"]
            next_handle.controller.fail_close = True
            request.query["playback_id"] = "next"
            try:
                await handler(request)
            except RuntimeError as exc:
                assert str(exc) == "uncertain teardown"
            else:
                raise AssertionError("teardown failure must propagate")
            assert app["playback_backends"]["draft:timeline"] is next_handle
            assert not next_handle.controller.closed and len(owners) == 2
            assert app["playback_backends"]["other:timeline"] is unrelated
            request.query["timeline"] = "fresh"
            assert (await handlers_backend.open_backend(request)).status == 200
            assert next_handle.controller.closed
            assert "draft:timeline" not in app["playback_backends"]
            await handlers_backend.close_backend(request)
        print(f"ok: canceled {action} awaits queued previous-owner close; unrelated key preserved")
        print(f"ok: failed {action} retains registry owner/executor for retry")


async def main():
    await queued_close_cancellation()
    events, live = [], {}
    failures = set()
    close_failures = set()
    probing = asyncio.Event()

    class View:
        did = "draft"

        def resolve_timeline(self, selector):
            return {"id": selector}

        def timeline_model(self, tid):
            return tid

    class Session:
        def view(self, selector):
            return View()

    class Handle:
        def __init__(self):
            self.playback_id = str(len(events))
            self.model = None
            events.append("construct")

        async def call(self, method, model):
            assert not any(getattr(owner, "teardown_failed", False) for owner in live.values()), "another key bypassed uncertain cleanup"
            assert model not in live, "replacement probe overlaps the previous native owner"
            self.model = model
            live[model] = self
            events.append("probe")
            if model == "canceled":
                probing.set()
                await asyncio.Event().wait()
            await asyncio.sleep(0.02)
            if model in failures:
                raise RuntimeError("failed probe")
            return {"playback_id": self.playback_id}

        async def close(self):
            if self.model in close_failures:
                close_failures.remove(self.model)
                raise RuntimeError("failed open cleanup")
            events.append("close-start")
            await asyncio.sleep(0.02)
            if live.get(self.model) is self:
                del live[self.model]
            events.append("close-done")

    root = Path("temp/backend-lifecycle")
    config = Config(drafts_root=root, jianying_root=root, install_root=root,
                    user_state_dir=root / "state")
    app = create_app(config, session=Session())
    async with AsyncExitStack() as stack:
        stack.enter_context(patch.object(handlers_backend, "PlaybackHandle", Handle))
        client = await stack.enter_async_context(TestClient(TestServer(app)))
        async def opened(timeline="stopped"):
            response = await client.post("/api/backend/open", params={"draft": "draft", "timeline": timeline})
            body = await response.json()
            assert response.status == 200, body
            return body["data"]["snapshot"]["playback_id"]

        for phase in ("stopped", "ended"):
            await opened(phase)
            events.clear()
            await opened(phase)
            assert events == ["close-start", "close-done", "construct", "probe"], events
        ids = await asyncio.gather(opened("parallel"), opened("parallel"))
        assert ids[0] != ids[1]
        assert live["parallel"].playback_id in ids
        discarded = next(identity for identity in ids if identity != live["parallel"].playback_id)
        stale = await client.post("/api/backend/close", params={"playback_id": discarded})
        assert stale.status == 404 and "parallel" in live
        await opened("failed")
        failures.add("failed")
        failed = await client.post("/api/backend/open", params={"draft": "draft", "timeline": "failed"})
        assert failed.status == 422
        assert "failed" not in live and "draft:failed" not in app["playback_backends"]
        close_failures.add("failed")
        uncertain = await client.post("/api/backend/open", params={"draft": "draft", "timeline": "failed"})
        assert uncertain.status == 500
        assert "failed" in live and "draft:failed" in app["playback_backends"], "uncertain new cleanup must retain its owner"
        fresh_id = await opened("fresh")
        assert "failed" not in live and "draft:failed" not in app["playback_backends"]
        await client.post("/api/backend/close", params={"draft": "draft", "timeline": "fresh", "playback_id": fresh_id})
        retried = await client.post("/api/backend/open", params={"draft": "draft", "timeline": "failed"})
        assert retried.status == 422 and "failed" not in live and "draft:failed" not in app["playback_backends"]
        request = SimpleNamespace(app=app, query={"draft": "draft", "timeline": "canceled"})
        canceled = asyncio.create_task(handlers_backend.open_backend(request))
        await probing.wait()
        canceled.cancel()
        try:
            await canceled
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("canceled open must propagate cancellation")
        assert "canceled" not in live and "draft:canceled" not in app["playback_backends"]
        assert not app["playback_lifecycle_lock"].locked()
        assert set(live) == {"stopped", "ended", "parallel"}, "independent keys must survive"
        for handle in list(app["playback_backends"].values()):
            await handle.close()
        app["playback_backends"].clear()
    assert not live
    print("ok: replacement ordering, parallel opens, failed/canceled probes, selector isolation")

    model = TimelineModel("failed", 1)
    compiled = CompiledTimeline(model, object(), SimpleNamespace(capture=None), 1, ())
    controller = PlaybackController()
    with patch.object(MltCompiler, "compile", return_value=compiled), \
            patch.object(MltCompiler, "_runtime", return_value=object()), \
            patch.object(PlaybackController, "_make_consumer", side_effect=RuntimeError("probe failed")):
        try:
            controller.open(model)
        except RuntimeError as exc:
            assert str(exc) == "probe failed"
        else:
            raise AssertionError("probe failure must propagate")
        finally:
            controller.close()
    assert compiled.tractor is None and compiled.profile is None
    assert controller._compiled is None and not controller._worker.is_alive()
    stopped = []
    def failed_position():
        raise RuntimeError("native read failed")
    consumer = SimpleNamespace(position=failed_position)
    with patch("jypreview.mlt_backend._start_consumer", return_value=0), \
            patch("jypreview.mlt_backend._stop_consumer", side_effect=lambda owner: stopped.append(owner)):
        try:
            PlaybackController._drives(consumer)
        except RuntimeError as exc:
            assert str(exc) == "native read failed"
        else:
            raise AssertionError("native read failure must propagate")
    assert stopped == [consumer], "a failed probe must stop its strongly held consumer"
    print("ok: failed probe retains compiled ownership until close and always stops its consumer")


if __name__ == "__main__":
    asyncio.run(main())
