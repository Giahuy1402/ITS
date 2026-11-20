"""Isolated browser smoke test: python scripts/smoke_browser.py."""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import urllib.request
import uvicorn
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    with tempfile.TemporaryDirectory(prefix="its-browser-") as temporary:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        previous_data_dir = os.environ.get("ITS_DATA_DIR")
        os.environ["ITS_DATA_DIR"] = temporary
        url = f"http://127.0.0.1:{port}"
        server = uvicorn.Server(uvicorn.Config("backend.app.main:app", host="127.0.0.1", port=port, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(url + "/api/health", timeout=1).close()
                    break
                except OSError:
                    if not thread.is_alive():
                        raise RuntimeError("Server stopped unexpectedly")
                    time.sleep(0.1)
            else:
                raise RuntimeError("Server startup timeout")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1080})
                errors = []
                frames = []
                page.on("pageerror", lambda err: errors.append(str(err)))
                page.on("dialog", lambda dialog: dialog.accept())
                page.on("websocket", lambda ws: ws.on("framereceived", lambda payload: frames.append(payload)))
                # Verify operation with every external request blocked.
                page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(url) else route.abort())
                page.goto(url, wait_until="networkidle")
                assert page.evaluate("typeof Chart") == "function"
                page.evaluate("loadSampleVideoAndStart(false)")
                page.wait_for_function("selectedVideo !== null && canvasEditor.bgLoaded")
                assert page.locator("#detection-mode").input_value() == "demo"
                page.locator("#advanced-setup summary").click()
                page.locator("#chk-enable-speed").check()
                page.locator("#input-distance-m").fill("10")
                # Exercise real pointer events, including the previously broken single click.
                page.evaluate("canvasEditor.lineA = null; canvasEditor.lineB = null; setDrawingTool('line_a')")
                surface = page.locator("#setup-canvas")
                surface.scroll_into_view_if_needed()
                box = surface.bounding_box()
                surface.click(position={"x": box["width"] * 0.25, "y": box["height"] * 0.3})
                assert page.evaluate("canvasEditor.getConfig().line_a === null && canvasEditor.dragState.waiting")
                surface.click(position={"x": box["width"] * 0.75, "y": box["height"] * 0.3})
                assert page.evaluate("canvasEditor.getConfig().line_a !== null && canvasEditor.dragState === null")
                page.evaluate("setDrawingTool('line_b')")
                box = surface.bounding_box()
                page.mouse.move(box["x"] + box["width"] * 0.25, box["y"] + box["height"] * 0.65)
                page.mouse.down()
                page.mouse.move(box["x"] + box["width"] * 0.75, box["y"] + box["height"] * 0.65, steps=8)
                page.mouse.up()
                assert page.evaluate("canvasEditor.getConfig().line_b !== null")
                # Keep the demo worker alive long enough to verify what users
                # actually see while analysis is still in progress.
                from backend.app.core.detector import DemoVehicleDetector
                original_detect = DemoVehicleDetector.detect
                def slowed_detect(self, *args, **kwargs):
                    time.sleep(0.04)
                    return original_detect(self, *args, **kwargs)
                DemoVehicleDetector.detect = slowed_detect
                page.locator("#btn-start-session").click()
                page.wait_for_function("liveOverlayFrames.size >= 10 && analysisRunning", timeout=20000)
                try:
                    page.wait_for_function("document.getElementById('output-video-player').currentTime > 0.1", timeout=10000)
                except Exception:
                    print(json.dumps({"playback_debug": page.evaluate("(() => { const p=document.getElementById('output-video-player'); return {time:p.currentTime, paused:p.paused, seeking:p.seeking, ready:p.readyState, width:p.videoWidth, height:p.videoHeight, firstLiveFrame, latestLiveFrame, livePlaybackWaiting, liveSeekTarget, mapSize:liveOverlayFrames.size, keys:[...liveOverlayFrames.keys()].slice(0,5), status:document.getElementById('session-status-title').textContent}; })()"), "page_errors": errors}, ensure_ascii=False))
                    raise
                try:
                    page.wait_for_function("(() => { const c=document.getElementById('live-overlay-canvas'); const data=c.getContext('2d').getImageData(0,0,c.width,c.height).data; for(let i=3;i<data.length;i+=4) if(data[i]) return true; return false; })()", timeout=10000)
                except Exception:
                    state = page.evaluate("(() => { const p=document.getElementById('output-video-player'); const c=document.getElementById('live-overlay-canvas'); const f=Math.floor(p.currentTime*selectedVideo.fps)+1; return {time:p.currentTime, paused:p.paused, seeking:p.seeking, ready:p.readyState, width:p.videoWidth, height:p.videoHeight, canvasWidth:c.width, canvasHeight:c.height, canvasDisplay:getComputedStyle(c).display, currentFrame:f, firstLiveFrame, latestLiveFrame, mapSize:liveOverlayFrames.size, tracksAtFrame:liveOverlayFrames.get(f)?.length, tracksNear:liveOverlayFrames.get(f-1)?.length, firstEntry:[...liveOverlayFrames.entries()][0], errors:window.__testErrors}; })()")
                    print(json.dumps({"live_debug": state, "page_errors": errors}, ensure_ascii=False))
                    raise
                live_bounds = page.evaluate("(() => { const v=document.getElementById('output-video-player').getBoundingClientRect(); const c=document.getElementById('live-overlay-canvas').getBoundingClientRect(); return {vw:v.width, vh:v.height, cw:c.width, ch:c.height, dx:c.left-v.left, dy:c.top-v.top}; })()")
                assert abs(live_bounds["vw"] - live_bounds["cw"]) < 1, live_bounds
                assert abs(live_bounds["vh"] - live_bounds["ch"]) < 1, live_bounds
                assert abs(live_bounds["dx"]) < 1 and abs(live_bounds["dy"]) < 1, live_bounds
                page.locator(".video-stage").screenshot(path=str(ROOT / "outputs" / "verification_live.png"))
                page.wait_for_function("document.getElementById('session-status-title').textContent.includes('hoàn tất thành công')", timeout=60000)
                DemoVehicleDetector.detect = original_detect
                page.wait_for_function("document.getElementById('output-video-player').readyState >= 2", timeout=15000)
                page.locator("#output-video-player").evaluate("video => video.play()")
                page.wait_for_function("document.getElementById('output-video-player').currentTime > 0.1")
                page.locator("#output-video-player").evaluate("video => video.pause()")
                stats = page.evaluate("({car:document.getElementById('count-car').textContent,motorcycle:document.getElementById('count-moto').textContent,truck:document.getElementById('count-truck').textContent,speed:document.getElementById('avg-speed-text').textContent})")
                assert frames and any('"kind":"tracks"' in str(frame).replace(" ", "") for frame in frames)
                assert not any('frame_jpeg' in str(frame) for frame in frames)
                assert page.evaluate("chartsController.chartFlowSpeed.data.labels.length") > 0
                with page.expect_download() as download:
                    page.locator("#btn-download-csv").click()
                assert download.value.suggested_filename.endswith(".csv")
                assert not errors, errors
                page.locator("#results-dashboard").screenshot(path=str(ROOT / "outputs" / "verification_dashboard.png"))
                page.evaluate("switchTab('settings')")
                page.locator("#setting-duration").fill("0")
                page.locator('.setting-cls[value="7"]').uncheck()
                page.evaluate("saveSystemSettings()")
                page.reload(wait_until="networkidle")
                assert page.locator("#setting-duration").input_value() == "0"
                assert not page.locator('.setting-cls[value="7"]').is_checked()
                page.evaluate("loadSampleVideoAndStart(false)")
                page.wait_for_function("selectedVideo !== null && canvasEditor.bgLoaded")
                page.locator("#advanced-setup summary").click()
                page.locator("#input-distance-m").fill("15")
                page.evaluate("openSavePresetModal()")
                page.locator("#preset-name-input").fill("<img src=x onerror=alert(1)>")
                page.evaluate("confirmSavePreset()")
                page.evaluate("switchTab('calibration')")
                page.wait_for_function("document.getElementById('preset-list').textContent.includes('<img')")
                assert page.locator("#preset-list img").count() == 0
                page.evaluate("applyPreset(1)")
                assert page.locator("#input-distance-m").input_value() == "15"
                page.set_viewport_size({"width": 390, "height": 844})
                page.evaluate("switchTab('analysis')")
                page.wait_for_timeout(350)
                assert page.locator(".main-content").bounding_box()["width"] >= 350
                assert page.locator("#setup-canvas").bounding_box()["width"] > 250
                page.screenshot(path=str(ROOT / "outputs" / "verification_mobile.png"), full_page=True)
                overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
                # Upload is the only interaction: no drawing and no Start button.
                import cv2
                import numpy as np
                upload_path = Path(temporary) / "upload_only.mp4"
                writer = cv2.VideoWriter(str(upload_path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 240))
                assert writer.isOpened()
                for _ in range(10):
                    writer.write(np.full((240, 320, 3), 50, np.uint8))
                writer.release()
                requests = []
                page.on("request", lambda request: requests.append(request.post_data_json)
                        if request.method == "POST" and request.url == url + "/api/sessions" else None)
                previous_session = page.evaluate("activeSessionId")
                page.locator("#video-file-input").set_input_files(str(upload_path))
                page.wait_for_function("old => activeSessionId !== old && !analysisRunning && !preparingVideo", arg=previous_session, timeout=60000)
                assert page.locator("#session-status-title").inner_text().endswith("thành công!")
                assert len(requests) == 1
                assert requests[0]["output_fps"] == 60
                assert 3 in requests[0]["target_classes"]
                assert requests[0]["counting_line"]["enabled"] is True
                assert requests[0]["speed_calibration"]["enabled"] is True
                assert requests[0]["speed_calibration"]["mode"] == "auto"
                assert requests[0]["speed_calibration"]["line_a"] is None
                assert page.locator("#detection-mode").input_value() == "yolo"
                assert page.locator("#input-distance-m").input_value() == ""
                assert "--" in page.locator("#avg-speed-text").inner_text()
                assert not errors, errors
                real_video = os.environ.get("ITS_TEST_REAL_VIDEO")
                if real_video:
                    page.set_viewport_size({"width": 1440, "height": 1080})
                    previous_session = page.evaluate("activeSessionId")
                    page.locator("#video-file-input").set_input_files(real_video)
                    page.wait_for_function("old => activeSessionId !== old && analysisRunning", arg=previous_session, timeout=60000)
                    page.wait_for_function("liveOverlayFrames.size >= 20 && document.getElementById('output-video-player').readyState >= 2", timeout=60000)
                    page.wait_for_function("(() => { const c=document.getElementById('live-overlay-canvas'); const data=c.getContext('2d').getImageData(0,0,c.width,c.height).data; for(let i=3;i<data.length;i+=4) if(data[i]) return true; return false; })()", timeout=30000)
                    real_bounds = page.evaluate("(() => { const v=document.getElementById('output-video-player').getBoundingClientRect(); const c=document.getElementById('live-overlay-canvas').getBoundingClientRect(); return {vw:v.width, vh:v.height, cw:c.width, ch:c.height, dx:c.left-v.left, dy:c.top-v.top}; })()")
                    assert abs(real_bounds["vw"] - real_bounds["cw"]) < 1, real_bounds
                    assert abs(real_bounds["vh"] - real_bounds["ch"]) < 1, real_bounds
                    page.locator(".video-stage").screenshot(path=str(ROOT / "outputs" / "verification_real_live.png"))
                    page.evaluate("document.getElementById('output-video-player').currentTime = 436")
                    page.wait_for_function("(() => { const p=document.getElementById('output-video-player'); return !p.seeking && p.currentTime < (latestLiveFrame + 4) / selectedVideo.fps; })()", timeout=15000)
                    page.locator("#btn-cancel-session").click()
                    page.wait_for_function("!analysisRunning", timeout=30000)
                    from backend.app.core.video_processor import CANCEL_REQUESTS
                    current_session = page.evaluate("activeSessionId")
                    for _ in range(200):
                        if current_session not in CANCEL_REQUESTS:
                            break
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("Cancelled worker did not stop")
                print(json.dumps({"browser": "chromium", "upload_only_auto_analysis": True, "offline_charts": True, "websocket_messages": len(frames),
                                  "video_playback": True, "csv_download": True, "settings_persisted": True,
                                  "preset_distance": 15, "mobile_overflow": overflow, "stats": stats}, ensure_ascii=True))
                browser.close()

        finally:
            server.should_exit = True
            thread.join(timeout=30)
            if thread.is_alive():
                from backend.app.api.sessions import manager
                import traceback
                stacks = {worker.name: traceback.format_stack(sys._current_frames()[worker.ident])[-8:]
                          for worker in threading.enumerate() if worker.ident in sys._current_frames()}
                print(json.dumps({"shutdown_debug": {"connections": len(server.server_state.connections),
                    "tasks": len(server.server_state.tasks),
                    "websockets": {str(key): len(value) for key, value in manager.active_connections.items()},
                    "should_exit": server.should_exit, "stacks": stacks}}, ensure_ascii=False))
                raise RuntimeError("Test server did not shut down")
            from backend.app.database import engine
            engine.dispose()
            if previous_data_dir is None:
                os.environ.pop("ITS_DATA_DIR", None)
            else:
                os.environ["ITS_DATA_DIR"] = previous_data_dir


if __name__ == "__main__":
    main()
