"""The few Xlib queries GTK does not offer, through ctypes (no extra package).

Tray hosts only tell us where the click happened. To open the panel beside
the bar rather than on top of it, we need the bar's rectangle: the topmost
mapped top-level window under that point. That works the same for eww,
polybar, tint2, xfce4-panel or any other X11 bar, with or without struts.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os

IS_VIEWABLE = 2
INPUT_ONLY = 2


class _XWindowAttributes(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int), ("y", ctypes.c_int),
        ("width", ctypes.c_int), ("height", ctypes.c_int),
        ("border_width", ctypes.c_int), ("depth", ctypes.c_int),
        ("visual", ctypes.c_void_p), ("root", ctypes.c_ulong),
        ("class_", ctypes.c_int), ("bit_gravity", ctypes.c_int),
        ("win_gravity", ctypes.c_int), ("backing_store", ctypes.c_int),
        ("backing_planes", ctypes.c_ulong), ("backing_pixel", ctypes.c_ulong),
        ("save_under", ctypes.c_int), ("colormap", ctypes.c_ulong),
        ("map_installed", ctypes.c_int), ("map_state", ctypes.c_int),
        ("all_event_masks", ctypes.c_long), ("your_event_mask", ctypes.c_long),
        ("do_not_propagate_mask", ctypes.c_long),
        ("override_redirect", ctypes.c_int), ("screen", ctypes.c_void_p),
    ]


_ERROR_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
_ignore_errors = _ERROR_HANDLER(lambda _display, _event: 0)
_lib = None
_display = None


def _xlib():
    global _lib
    if _lib is None:
        name = ctypes.util.find_library("X11") or "libX11.so.6"
        lib = ctypes.CDLL(name)
        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        lib.XDefaultRootWindow.restype = ctypes.c_ulong
        lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        lib.XQueryTree.restype = ctypes.c_int
        lib.XQueryTree.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
            ctypes.POINTER(ctypes.c_uint)]
        lib.XGetWindowAttributes.restype = ctypes.c_int
        lib.XGetWindowAttributes.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_XWindowAttributes)]
        lib.XFree.argtypes = [ctypes.c_void_p]
        lib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.XSetErrorHandler.restype = ctypes.c_void_p
        lib.XSetErrorHandler.argtypes = [ctypes.c_void_p]
        _lib = lib
    return _lib


def _connection():
    """A private connection, kept open, so GDK's own is never disturbed."""
    global _display
    if _display is None:
        name = os.environ.get("DISPLAY")
        if not name:
            return None, None
        lib = _xlib()
        _display = lib.XOpenDisplay(name.encode())
        if not _display:
            _display = None
            return lib, None
    return _xlib(), _display


def toplevel_rect_at(x, y, ignore=()):
    """(x, y, width, height) of the topmost viewable top-level window containing
    the root-coordinate point, skipping screen-sized windows. None if unknown."""
    try:
        lib, display = _connection()
    except OSError:
        return None
    if display is None:
        return None
    # Windows can vanish between QueryTree and GetWindowAttributes; Xlib's
    # default handler would exit the process. Swap in a no-op handler for the
    # duration of this synchronous query only, then restore GDK's.
    previous = lib.XSetErrorHandler(ctypes.cast(_ignore_errors, ctypes.c_void_p))
    try:
        root = lib.XDefaultRootWindow(display)
        root_attrs = _XWindowAttributes()
        if not lib.XGetWindowAttributes(display, root, ctypes.byref(root_attrs)):
            return None
        root_ret, parent_ret = ctypes.c_ulong(), ctypes.c_ulong()
        children = ctypes.POINTER(ctypes.c_ulong)()
        count = ctypes.c_uint()
        if not lib.XQueryTree(display, root, ctypes.byref(root_ret), ctypes.byref(parent_ret),
                              ctypes.byref(children), ctypes.byref(count)):
            return None
        try:
            windows = [children[i] for i in range(count.value)]
        finally:
            if children:
                lib.XFree(children)
        attrs = _XWindowAttributes()
        # QueryTree lists children bottom to top.
        for window in reversed(windows):
            if window in ignore:
                continue
            if not lib.XGetWindowAttributes(display, window, ctypes.byref(attrs)):
                continue
            if attrs.map_state != IS_VIEWABLE or attrs.class_ == INPUT_ONLY:
                continue
            w = attrs.width + 2 * attrs.border_width
            h = attrs.height + 2 * attrs.border_width
            if not (attrs.x <= x < attrs.x + w and attrs.y <= y < attrs.y + h):
                continue
            if w >= root_attrs.width and h >= root_attrs.height:
                continue      # desktop, overlay or full-screen window: not a bar
            return attrs.x, attrs.y, w, h
        return None
    finally:
        lib.XSync(display, 0)
        lib.XSetErrorHandler(previous)
