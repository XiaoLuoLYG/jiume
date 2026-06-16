"""Transparent desktop overlay adapters for the JiuMe avatar UI."""

from __future__ import annotations

import sys
import tkinter as tk
from collections import deque
from io import BytesIO
from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable, Literal

from PIL import Image


LayerKind = Literal["avatar", "bubble", "cards", "chat", "panel"]
AVATAR_DRAG_THRESHOLD_PX = 3


@dataclass(frozen=True)
class AvatarLayer:
    """Rendering contract for the avatar-only desktop layer."""

    kind: LayerKind = "avatar"


@dataclass(frozen=True)
class BubbleLayer:
    """Rendering contract for speech and comic chat bubbles."""

    kind: LayerKind = "bubble"


@dataclass(frozen=True)
class FloatingCardLayer:
    """Rendering contract for state-aware right-click cards."""

    kind: LayerKind = "cards"


class DesktopOverlayHost:
    """Apply native transparent-window behavior while keeping Tk as fallback."""

    def __init__(self, root: tk.Misc, *, transparent_bg: str) -> None:
        self.root = root
        self.transparent_bg = transparent_bg
        self._windows: list[tuple[tk.Misc, LayerKind]] = []
        self._window_titles: dict[int, str] = {}
        self._has_appkit = sys.platform == "darwin"
        self._avatar_window: object | None = None
        self._avatar_view: object | None = None
        self._avatar_callbacks: dict[str, Callable[..., None]] = {}
        self._avatar_drag_origin: tuple[float, float, int, int] | None = None
        self._avatar_dragging_native = False
        self._avatar_dragged = False
        self._pending_avatar_events: deque[tuple[str, tuple[object, ...]]] = deque()
        self._pending_avatar_events_lock = Lock()
        self._pending_layer_callbacks: deque[Callable[[], None]] = deque()
        self._pending_layer_callbacks_lock = Lock()
        self._avatar_event_polling = False
        self._image_layers: dict[str, dict[str, Any]] = {}

    def native_backing_scale(self) -> float:
        """Return the current macOS backing scale for crisp transparent layers."""
        if not self._has_appkit:
            return 1.0
        for window in (self._avatar_window, *[state.get("window") for state in self._image_layers.values()]):
            if window is None:
                continue
            try:
                scale = float(window.backingScaleFactor())  # type: ignore[attr-defined]
            except Exception:
                continue
            if scale >= 1.0:
                return min(3.0, scale)
        try:
            from AppKit import NSScreen  # type: ignore[import-not-found]

            screen = NSScreen.mainScreen()
            scale = float(screen.backingScaleFactor()) if screen is not None else 1.0
            return max(1.0, min(3.0, scale))
        except Exception:
            return 2.0 if sys.platform == "darwin" else 1.0

    def _retina_image(self, image: Image.Image, *, logical_width: int, logical_height: int) -> Image.Image:
        rgba = image.convert("RGBA")
        scale = self.native_backing_scale()
        target = (
            max(1, int(round(int(logical_width) * scale))),
            max(1, int(round(int(logical_height) * scale))),
        )
        if rgba.size != target:
            rgba = rgba.resize(target, Image.Resampling.LANCZOS)
        return rgba

    def apply_avatar_window(self, window: tk.Misc, *, title: str = "") -> None:
        self._prepare_tk_window(window, kind="avatar", title=title)
        self._remember(window, "avatar")
        self._defer_native_apply(window, "avatar")
        if self._has_appkit:
            self._ensure_native_avatar_window(window)
            try:
                window.after(120, window.withdraw)  # type: ignore[attr-defined]
            except tk.TclError:
                pass

    def apply_transparent_layer(self, window: tk.Misc, *, kind: LayerKind = "panel") -> None:
        self._prepare_tk_window(window, kind=kind)
        self._remember(window, kind)
        self._defer_native_apply(window, kind)

    def create_layer_window(
        self,
        parent: tk.Misc,
        *,
        kind: LayerKind,
        width: int | None = None,
        height: int | None = None,
    ) -> tk.Toplevel:
        window = tk.Toplevel(parent)
        if width and height:
            window.geometry(f"{int(width)}x{int(height)}")
        self.apply_transparent_layer(window, kind=kind)
        return window

    def refresh(self) -> None:
        for window, kind in list(self._windows):
            try:
                if not bool(window.winfo_exists()):
                    continue
            except tk.TclError:
                continue
            self._prepare_tk_window(window, kind=kind)
            self._apply_appkit_window(window, kind)
        if self._has_appkit:
            self._sync_native_avatar_frame()

    def set_avatar_callbacks(self, **callbacks: Callable[..., None]) -> None:
        self._avatar_callbacks = dict(callbacks)
        if callbacks:
            self._ensure_avatar_event_polling()

    def update_avatar_image(self, image: Image.Image, *, x: int, y: int, size: int) -> None:
        if not self._has_appkit:
            return
        self._ensure_native_avatar_window(self.root)
        if self._avatar_window is None or self._avatar_view is None:
            return
        try:
            from AppKit import NSData, NSImage, NSMakeSize  # type: ignore[import-not-found]
        except Exception:
            return
        rgba = self._retina_image(image, logical_width=size, logical_height=size)
        buffer = BytesIO()
        rgba.save(buffer, format="PNG")
        payload = buffer.getvalue()
        data = NSData.dataWithBytes_length_(payload, len(payload))
        ns_image = NSImage.alloc().initWithData_(data)
        try:
            ns_image.setSize_(NSMakeSize(int(size), int(size)))
            self._avatar_view.setImage_(ns_image)  # type: ignore[attr-defined]
            if not self._avatar_dragging_native:
                self._set_native_avatar_frame(x=x, y=y, size=size)
            self._avatar_window.orderFrontRegardless()  # type: ignore[attr-defined]
        except Exception:
            return

    def show_image_layer(
        self,
        layer_id: str,
        image: Image.Image,
        *,
        x: int,
        y: int,
        click_zones: list[tuple[int, int, int, int, str]] | None = None,
        on_click: Callable[[str], None] | None = None,
        on_scroll: Callable[[float], None] | None = None,
        text_input: dict[str, Any] | None = None,
        logical_size: tuple[int, int] | None = None,
    ) -> None:
        if not self._has_appkit:
            return
        try:
            import objc  # type: ignore[import-not-found]
            from AppKit import (  # type: ignore[import-not-found]
                NSBackingStoreBuffered,
                NSColor,
                NSFloatingWindowLevel,
                NSFont,
                NSImage,
                NSImageScaleAxesIndependently,
                NSImageView,
                NSMakeRect,
                NSMakeSize,
                NSObject,
                NSStatusWindowLevel,
                NSWindowCollectionBehaviorCanJoinAllSpaces,
                NSWindowCollectionBehaviorFullScreenAuxiliary,
                NSWindow,
                NSWindowStyleMaskBorderless,
                NSTextField,
            )
        except Exception:
            return

        key = str(layer_id or "layer")
        logical_width, logical_height = logical_size or image.size
        width = max(1, int(logical_width))
        height = max(1, int(logical_height))
        rgba = self._retina_image(image, logical_width=width, logical_height=height)
        buffer = BytesIO()
        rgba.save(buffer, format="PNG")
        payload = buffer.getvalue()
        try:
            from AppKit import NSData  # type: ignore[import-not-found]
        except Exception:
            return
        data = NSData.dataWithBytes_length_(payload, len(payload))
        ns_image = NSImage.alloc().initWithData_(data)
        try:
            ns_image.setSize_(NSMakeSize(width, height))
        except Exception:
            pass
        zones = list(click_zones or [])

        state = self._image_layers.get(key)

        if state is None:
            try:
                overlay_window_class = objc.lookUpClass("JiuMeOverlayWindow")
            except objc.error:
                class JiuMeOverlayWindow(NSWindow):  # type: ignore[misc, valid-type]
                    def canBecomeKeyWindow(self):  # noqa: N802
                        return True

                    def canBecomeMainWindow(self):  # noqa: N802
                        return True

                overlay_window_class = JiuMeOverlayWindow

            try:
                image_view_class = objc.lookUpClass("JiuMeImageLayerView")
            except objc.error:
                class JiuMeImageLayerView(NSImageView):  # type: ignore[misc, valid-type]
                    def initWithFrame_(self, frame):  # noqa: N802
                        self = objc.super(JiuMeImageLayerView, self).initWithFrame_(frame)
                        if self is None:
                            return None
                        self.host = None
                        self.clickZones = []
                        self.clickCallback = None
                        self.scrollCallback = None
                        self.textField = None
                        self.submitCallback = None
                        self.setImageScaling_(NSImageScaleAxesIndependently)
                        return self

                    def isFlipped(self):  # noqa: N802
                        return True

                    def acceptsFirstMouse_(self, event):  # noqa: N802
                        return True

                    def mouseDown_(self, event):  # noqa: N802
                        if self.host is None or self.clickCallback is None:
                            return
                        point = self.convertPoint_fromView_(event.locationInWindow(), None)
                        px = int(point.x)
                        py = int(point.y)
                        for zx, zy, zw, zh, action in self.clickZones:
                            if zx <= px <= zx + zw and zy <= py <= zy + zh:
                                if action in {"run_submit", "send"} and self.host is not None and self.textField is not None and callable(self.submitCallback):
                                    value = str(self.textField.stringValue())
                                    self.textField.setStringValue_("")
                                    host = self.host
                                    callback = self.submitCallback
                                    host._queue_layer_callback(lambda text=value, cb=callback: cb(text))
                                    return
                                callback = self.clickCallback
                                host = self.host
                                host._queue_layer_callback(lambda value=action, cb=callback: cb(value))
                                return

                    def rightMouseDown_(self, event):  # noqa: N802
                        self.mouseDown_(event)

                    def scrollWheel_(self, event):  # noqa: N802
                        if self.host is None or self.scrollCallback is None:
                            return
                        try:
                            delta = float(event.scrollingDeltaY())
                        except Exception:
                            delta = 0.0
                        if abs(delta) < 0.01:
                            return
                        host = self.host
                        callback = self.scrollCallback
                        host._queue_layer_callback(lambda value=delta, cb=callback: cb(value))

                image_view_class = JiuMeImageLayerView

            rect = NSMakeRect(0, 0, int(width), int(height))
            ns_window = overlay_window_class.alloc().initWithContentRect_styleMask_backing_defer_(
                rect,
                NSWindowStyleMaskBorderless,
                NSBackingStoreBuffered,
                False,
            )
            ns_window.setBackgroundColor_(NSColor.clearColor())
            ns_window.setOpaque_(False)
            ns_window.setHasShadow_(False)
            ns_window.setIgnoresMouseEvents_(False)
            ns_window.setLevel_(NSStatusWindowLevel)
            ns_window.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary
            )
            view = image_view_class.alloc().initWithFrame_(rect)
            view.host = self
            try:
                view.setWantsLayer_(True)
                layer = view.layer()
                if layer is not None:
                    layer.setBackgroundColor_(NSColor.clearColor().CGColor())
                    layer.setOpaque_(False)
                    try:
                        layer.setContentsScale_(self.native_backing_scale())
                    except Exception:
                        pass
            except Exception:
                pass
            ns_window.setContentView_(view)
            state = {
                "window": ns_window,
                "view": view,
                "target": None,
                "text_field": None,
                "image": None,
                "visible": False,
            }
            self._image_layers[key] = state

        ns_window = state["window"]
        view = state["view"]
        frame = NSMakeRect(0, 0, int(width), int(height))
        try:
            view.setFrame_(frame)
            view.setImage_(ns_image)
            try:
                view.setWantsLayer_(True)
                layer = view.layer()
                if layer is not None:
                    layer.setBackgroundColor_(NSColor.clearColor().CGColor())
                    layer.setOpaque_(False)
                    try:
                        layer.setContentsScale_(self.native_backing_scale())
                    except Exception:
                        pass
            except Exception:
                pass
            view.clickZones = zones
            view.clickCallback = on_click
            view.scrollCallback = on_scroll
            view.setNeedsDisplay_(True)
            ns_window.setContentSize_(frame.size)
            self._set_image_layer_frame(ns_window, x=int(x), y=int(y), width=int(width), height=int(height))
            view.display()
            ns_window.display()
        except Exception:
            return

        old_field = state.get("text_field")
        if old_field is not None:
            try:
                old_field.removeFromSuperview()
            except Exception:
                pass
            state["text_field"] = None
            state["target"] = None
            try:
                view.textField = None
                view.submitCallback = None
            except Exception:
                pass

        if text_input:
            on_submit = text_input.get("on_submit")
            field_frame = text_input.get("frame") or (0, 0, 120, 28)
            try:
                fx, fy, fw, fh = [int(value) for value in field_frame]
            except Exception:
                fx, fy, fw, fh = 0, 0, 120, 28

            try:
                text_target_class = objc.lookUpClass("JiuMeOverlayTextTarget")
            except objc.error:
                class JiuMeOverlayTextTarget(NSObject):  # type: ignore[misc, valid-type]
                    def init(self):  # noqa: N802
                        self = objc.super(JiuMeOverlayTextTarget, self).init()
                        if self is None:
                            return None
                        self.host = None
                        self.onSubmit = None
                        return self

                    def submit_(self, sender):  # noqa: N802
                        value = str(sender.stringValue())
                        sender.setStringValue_("")
                        if self.host is not None and callable(self.onSubmit):
                            host = self.host
                            callback = self.onSubmit
                            host._queue_layer_callback(lambda text=value, cb=callback: cb(text))

                text_target_class = JiuMeOverlayTextTarget

            target = text_target_class.alloc().init()
            target.host = self
            target.onSubmit = on_submit
            field = NSTextField.alloc().initWithFrame_(NSMakeRect(fx, fy, fw, fh))
            field.setBezeled_(False)
            field.setDrawsBackground_(False)
            field.setBordered_(False)
            field.setFocusRingType_(1)
            try:
                font_size = max(10, min(18, int(text_input.get("font_size") or 14)))
            except Exception:
                font_size = 14
            field.setFont_(NSFont.systemFontOfSize_(font_size))
            text_color = str(text_input.get("text_color") or "#17191D").lstrip("#")
            if len(text_color) == 6:
                try:
                    red = int(text_color[0:2], 16) / 255.0
                    green = int(text_color[2:4], 16) / 255.0
                    blue = int(text_color[4:6], 16) / 255.0
                    field.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(red, green, blue, 1.0))
                except Exception:
                    pass
            field.setPlaceholderString_(str(text_input.get("placeholder") or ""))
            field.setStringValue_(str(text_input.get("value") or ""))
            field.setTarget_(target)
            field.setAction_("submit:")
            view.addSubview_(field)
            try:
                view.textField = field
                view.submitCallback = on_submit
            except Exception:
                pass
            state["target"] = target
            state["text_field"] = field
            ns_window.makeKeyAndOrderFront_(None)
            try:
                ns_window.makeFirstResponder_(field)
            except Exception:
                pass
        else:
            ns_window.orderFrontRegardless()
        state["image"] = ns_image
        state["visible"] = True

    def hide_image_layer(self, layer_id: str) -> None:
        state = self._image_layers.get(str(layer_id or "layer"))
        if not state:
            return
        try:
            state["window"].orderOut_(None)
        except Exception:
            pass
        state["visible"] = False

    def is_image_layer_visible(self, layer_id: str) -> bool:
        state = self._image_layers.get(str(layer_id or "layer"))
        return bool(state and state.get("visible"))

    def _remember(self, window: tk.Misc, kind: LayerKind) -> None:
        self._windows = [(existing, existing_kind) for existing, existing_kind in self._windows if existing is not window]
        self._windows.append((window, kind))

    def _defer_native_apply(self, window: tk.Misc, kind: LayerKind) -> None:
        self._apply_appkit_window(window, kind)
        for delay in (0, 80, 240):
            try:
                window.after(delay, lambda target=window, layer=kind: self._apply_appkit_window(target, layer))
            except tk.TclError:
                break

    def _prepare_tk_window(self, window: tk.Misc, *, kind: LayerKind, title: str = "") -> None:
        try:
            window_title = title or self._window_titles.get(id(window)) or f"JiuMe {kind} Overlay {id(window)}"
            self._window_titles[id(window)] = window_title
            window.title(window_title)  # type: ignore[attr-defined]
            if kind != "avatar" or not self._has_appkit:
                window.overrideredirect(True)  # type: ignore[attr-defined]
            window.attributes("-topmost", True)  # type: ignore[attr-defined]
            window.configure(bg=self.transparent_bg)
            if not self._has_appkit:
                window.wm_attributes("-transparentcolor", self.transparent_bg)  # type: ignore[attr-defined]
            if kind == "avatar":
                window.attributes("-alpha", 1.0)  # type: ignore[attr-defined]
        except tk.TclError:
            return

    def _apply_appkit_window(self, window: tk.Misc, kind: LayerKind) -> None:
        if not self._has_appkit:
            return
        try:
            from AppKit import (  # type: ignore[import-not-found]
                NSApplication,
                NSColor,
                NSFloatingWindowLevel,
                NSStatusWindowLevel,
                NSWindowCollectionBehaviorCanJoinAllSpaces,
                NSWindowCollectionBehaviorFullScreenAuxiliary,
                NSWindowStyleMaskBorderless,
            )
        except Exception:
            return
        try:
            window.update_idletasks()
            target_title = self._window_titles.get(id(window), "")
            for ns_window in NSApplication.sharedApplication().windows():
                if target_title and str(ns_window.title()) != target_title:
                    continue
                ns_window.setStyleMask_(NSWindowStyleMaskBorderless)
                ns_window.setBackgroundColor_(NSColor.clearColor())
                ns_window.setOpaque_(False)
                ns_window.setHasShadow_(kind != "avatar")
                ns_window.setIgnoresMouseEvents_(False)
                ns_window.setLevel_(NSStatusWindowLevel)
                ns_window.setCollectionBehavior_(
                    NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary
                )
        except Exception:
            return

    def _ensure_native_avatar_window(self, window: tk.Misc) -> None:
        if self._avatar_window is not None and self._avatar_view is not None:
            return
        try:
            import objc  # type: ignore[import-not-found]
            from AppKit import (  # type: ignore[import-not-found]
                NSBackingStoreBuffered,
                NSColor,
                NSFloatingWindowLevel,
                NSImageScaleProportionallyUpOrDown,
                NSMakeRect,
                NSEvent,
                NSStatusWindowLevel,
                NSTrackingActiveAlways,
                NSTrackingArea,
                NSTrackingMouseEnteredAndExited,
                NSTrackingMouseMoved,
                NSView,
                NSWindow,
                NSWindowCollectionBehaviorCanJoinAllSpaces,
                NSWindowCollectionBehaviorFullScreenAuxiliary,
                NSWindowStyleMaskBorderless,
            )
        except Exception:
            return

        host = self

        class _JiuMeAvatarImageView(NSView):  # type: ignore[misc, valid-type]
            def initWithFrame_(self, frame):  # noqa: N802
                self = objc.super(_JiuMeAvatarImageView, self).initWithFrame_(frame)
                if self is None:
                    return None
                self.imageView = None
                return self

            def setImageView_(self, image_view):  # noqa: N802
                self.imageView = image_view
                self.addSubview_(image_view)

            def acceptsFirstMouse_(self, event):  # noqa: N802
                return True

            def updateTrackingAreas(self):  # noqa: N802
                objc.super(_JiuMeAvatarImageView, self).updateTrackingAreas()
                area = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
                    self.bounds(),
                    NSTrackingActiveAlways | NSTrackingMouseEnteredAndExited | NSTrackingMouseMoved,
                    self,
                    None,
                )
                self.addTrackingArea_(area)

            def mouseEntered_(self, event):  # noqa: N802
                host._invoke_avatar_callback("enter")

            def mouseExited_(self, event):  # noqa: N802
                host._invoke_avatar_callback("leave")

            def mouseDown_(self, event):  # noqa: N802
                loc = NSEvent.mouseLocation()
                frame = self.window().frame()
                host._avatar_drag_origin = (float(loc.x), float(loc.y), int(frame.origin.x), int(frame.origin.y))
                host._avatar_dragging_native = True
                host._avatar_dragged = False

            def mouseDragged_(self, event):  # noqa: N802
                if host._avatar_drag_origin is None:
                    return
                start_x, start_y, win_x, win_y = host._avatar_drag_origin
                loc = NSEvent.mouseLocation()
                dx = float(loc.x) - start_x
                dy = float(loc.y) - start_y
                if not host._avatar_dragged and abs(dx) <= AVATAR_DRAG_THRESHOLD_PX and abs(dy) <= AVATAR_DRAG_THRESHOLD_PX:
                    return
                if abs(dx) > AVATAR_DRAG_THRESHOLD_PX or abs(dy) > AVATAR_DRAG_THRESHOLD_PX:
                    host._avatar_dragged = True
                frame = self.window().frame()
                frame.origin.x = win_x + dx
                frame.origin.y = win_y + dy
                self.window().setFrame_display_(frame, True)
                host._sync_tk_from_native_frame(frame, final=False)

            def mouseUp_(self, event):  # noqa: N802
                dragged = host._avatar_dragged
                if dragged:
                    frame = self.window().frame()
                    host._sync_tk_from_native_frame(frame, final=True)
                host._avatar_drag_origin = None
                host._avatar_dragging_native = False
                host._avatar_dragged = False
                host._invoke_avatar_callback("left_click", dragged)

            def rightMouseDown_(self, event):  # noqa: N802
                host._invoke_avatar_callback("right_click")

        rect = NSMakeRect(0, 0, 128, 128)
        ns_window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        ns_window.setBackgroundColor_(NSColor.clearColor())
        ns_window.setOpaque_(False)
        ns_window.setHasShadow_(False)
        ns_window.setLevel_(NSStatusWindowLevel)
        ns_window.setIgnoresMouseEvents_(False)
        ns_window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        from AppKit import NSImageView  # type: ignore[import-not-found]

        view = _JiuMeAvatarImageView.alloc().initWithFrame_(rect)
        image_view = NSImageView.alloc().initWithFrame_(rect)
        image_view.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        image_view.setEditable_(False)
        image_view.setAllowsCutCopyPaste_(False)
        try:
            view.setWantsLayer_(True)
            image_view.setWantsLayer_(True)
            for native_view in (view, image_view):
                layer = native_view.layer()
                if layer is not None:
                    layer.setBackgroundColor_(NSColor.clearColor().CGColor())
                    layer.setOpaque_(False)
                    try:
                        layer.setContentsScale_(self.native_backing_scale())
                    except Exception:
                        pass
        except Exception:
            pass
        view.setImageView_(image_view)
        ns_window.setContentView_(view)
        self._avatar_window = ns_window
        self._avatar_view = image_view
        self._sync_native_avatar_frame()

    def _set_native_avatar_frame(self, *, x: int, y: int, size: int) -> None:
        if self._avatar_window is None:
            return
        try:
            from AppKit import NSMakeRect  # type: ignore[import-not-found]
            screen_height = int(self.root.winfo_screenheight())
            frame = NSMakeRect(int(x), int(screen_height - y - size), int(size), int(size))
            self._avatar_window.setFrame_display_(frame, True)  # type: ignore[attr-defined]
            if self._avatar_view is not None:
                self._avatar_view.setFrame_(NSMakeRect(0, 0, int(size), int(size)))  # type: ignore[attr-defined]
        except Exception:
            return

    def _set_image_layer_frame(self, ns_window: object, *, x: int, y: int, width: int, height: int) -> None:
        try:
            from AppKit import NSMakeRect  # type: ignore[import-not-found]
            screen_height = int(self.root.winfo_screenheight())
            frame = NSMakeRect(int(x), int(screen_height - y - height), int(width), int(height))
            ns_window.setFrame_display_(frame, True)  # type: ignore[attr-defined]
        except Exception:
            return

    def _sync_native_avatar_frame(self) -> None:
        try:
            self._set_native_avatar_frame(
                x=int(self.root.winfo_x()),
                y=int(self.root.winfo_y()),
                size=max(1, int(self.root.winfo_width() or self.root.winfo_reqwidth())),
            )
        except tk.TclError:
            return

    def _sync_tk_from_native_frame(self, frame: object, *, final: bool = False) -> None:
        try:
            x = int(frame.origin.x)  # type: ignore[attr-defined]
            native_y = int(frame.origin.y)  # type: ignore[attr-defined]
            height = int(frame.size.height)  # type: ignore[attr-defined]
        except Exception:
            return
        self._queue_avatar_event("_native_move_frame", x, native_y, height, bool(final))

    def _invoke_avatar_callback(self, name: str, *args: object) -> None:
        if name in self._avatar_callbacks:
            self._queue_avatar_event(name, *args)

    def _queue_avatar_event(self, name: str, *args: object) -> None:
        with self._pending_avatar_events_lock:
            self._pending_avatar_events.append((name, args))

    def _queue_layer_callback(self, callback: Callable[[], None]) -> None:
        with self._pending_layer_callbacks_lock:
            self._pending_layer_callbacks.append(callback)
        self._ensure_avatar_event_polling()

    def _ensure_avatar_event_polling(self) -> None:
        if self._avatar_event_polling:
            return
        self._avatar_event_polling = True
        try:
            self.root.after(16, self._drain_avatar_events)
        except tk.TclError:
            self._avatar_event_polling = False

    def _drain_avatar_events(self) -> None:
        events: list[tuple[str, tuple[object, ...]]] = []
        layer_callbacks: list[Callable[[], None]] = []
        with self._pending_avatar_events_lock:
            while self._pending_avatar_events:
                events.append(self._pending_avatar_events.popleft())
        with self._pending_layer_callbacks_lock:
            while self._pending_layer_callbacks:
                layer_callbacks.append(self._pending_layer_callbacks.popleft())

        for name, args in events:
            if name == "_native_move_frame":
                self._apply_native_move_event(*args)
                continue
            self._run_avatar_callback(name, *args)
        for callback in layer_callbacks:
            try:
                callback()
            except Exception:
                continue

        if not self._avatar_event_polling:
            return
        try:
            self.root.after(16, self._drain_avatar_events)
        except tk.TclError:
            self._avatar_event_polling = False

    def _apply_native_move_event(
        self,
        x_value: object,
        native_y_value: object,
        height_value: object,
        final_value: object = False,
    ) -> None:
        try:
            screen_height = int(self.root.winfo_screenheight())
            x = int(x_value)
            y = int(screen_height - int(native_y_value) - int(height_value))
            self.root.geometry(f"+{x}+{y}")
        except (tk.TclError, TypeError, ValueError):
            return
        self._run_avatar_callback("move", x, y)

    def _run_avatar_callback(self, name: str, *args: object) -> None:
        callback = self._avatar_callbacks.get(name)
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:
            return
