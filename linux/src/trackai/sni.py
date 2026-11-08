"""A StatusNotifierItem served directly over D-Bus (replaces libappindicator).

libappindicator always marks its item as menu-only, so every tray host opens a
menu on a left click and there is no way to show our own panel. Serving the
item ourselves lets the click reach ``Activate(x, y)``: we open the panel at
the icon.

``Title`` and ``ToolTip`` stay empty on purpose. Hosts render them as a hover
tooltip (eww shows ``Title``; KDE, waybar and the GNOME extension show
``ToolTip``), and trackai has no hover. Only Gio is used, so there is no extra
dependency.
"""

from __future__ import annotations

import os
import sys

from gi.repository import Gio, GLib

WATCHER = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
ITEM_PATH = "/StatusNotifierItem"
ITEM_IFACE = "org.kde.StatusNotifierItem"

_XY = '<arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/>'
INTROSPECTION = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionMovieName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="XAyatanaLabel" type="s" access="read"/>
    <property name="XAyatanaLabelGuide" type="s" access="read"/>
    <method name="ContextMenu">%(xy)s</method>
    <method name="Activate">%(xy)s</method>
    <method name="SecondaryActivate">%(xy)s</method>
    <method name="Scroll">
      <arg name="delta" type="i" direction="in"/>
      <arg name="orientation" type="s" direction="in"/>
    </method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewAttentionIcon"/>
    <signal name="NewOverlayIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus"><arg name="status" type="s"/></signal>
    <signal name="XAyatanaNewLabel">
      <arg name="label" type="s"/>
      <arg name="guide" type="s"/>
    </signal>
  </interface>
</node>
""" % {"xy": _XY}

_TYPES = {
    "Category": "s", "Id": "s", "Title": "s", "Status": "s", "WindowId": "i",
    "IconThemePath": "s", "IconName": "s", "IconPixmap": "a(iiay)",
    "OverlayIconName": "s", "OverlayIconPixmap": "a(iiay)",
    "AttentionIconName": "s", "AttentionIconPixmap": "a(iiay)",
    "AttentionMovieName": "s", "ToolTip": "(sa(iiay)ss)", "ItemIsMenu": "b",
    "XAyatanaLabel": "s", "XAyatanaLabelGuide": "s",
}


class StatusNotifierItem(object):
    """One tray item. ``on_activate(x, y)`` runs on any click.

    ``on_host_changed(available)`` reports whether a tray host (watcher) is
    present, so the caller can fall back to an XEmbed icon when it is not.
    """

    def __init__(self, item_id, on_activate, on_host_changed=None):
        self.on_activate = on_activate
        self.on_host_changed = on_host_changed or (lambda _available: None)
        self.registered = False
        self._values = {
            "Category": "ApplicationStatus",
            "Id": item_id,
            "Title": "",
            "Status": "Active",
            "WindowId": 0,
            "IconThemePath": "",
            "IconName": "",
            "IconPixmap": [],
            "OverlayIconName": "",
            "OverlayIconPixmap": [],
            "AttentionIconName": "",
            "AttentionIconPixmap": [],
            "AttentionMovieName": "",
            "ToolTip": ("", [], "", ""),
            "ItemIsMenu": False,
            "XAyatanaLabel": "",
            "XAyatanaLabelGuide": "",
        }
        self._bus = None
        self._name = "org.kde.StatusNotifierItem-{}-1".format(os.getpid())
        self._object_id = 0
        self._owner_id = 0
        self._watch_id = 0

    # -- lifecycle ---------------------------------------------------------

    def start(self):
        # type: () -> bool
        """Export the item and wait for a watcher. False when D-Bus is unusable."""
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            info = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION).interfaces[0]
            self._object_id = self._bus.register_object(
                ITEM_PATH, info, self._on_method_call, self._on_get_property, None)
        except (GLib.Error, TypeError) as err:
            sys.stderr.write("trackai: cannot export the tray item on D-Bus ({}).\n".format(err))
            self._bus = None
            return False
        self._owner_id = Gio.bus_own_name_on_connection(
            self._bus, self._name, Gio.BusNameOwnerFlags.NONE, None, None)
        self._watch_id = Gio.bus_watch_name_on_connection(
            self._bus, WATCHER, Gio.BusNameWatcherFlags.NONE,
            self._on_watcher_appeared, self._on_watcher_vanished)
        return True

    def stop(self):
        if self._bus is None:
            return
        if self._watch_id:
            Gio.bus_unwatch_name(self._watch_id)
        if self._owner_id:
            Gio.bus_unown_name(self._owner_id)
        if self._object_id:
            self._bus.unregister_object(self._object_id)
        self._bus = None

    # A tray host restarting (eww reloads with i3, for instance) brings a new
    # watcher; register again every time one appears.
    def _on_watcher_appeared(self, bus, _name, _owner):
        bus.call(WATCHER, WATCHER_PATH, WATCHER, "RegisterStatusNotifierItem",
                 GLib.Variant("(s)", (self._name,)), None,
                 Gio.DBusCallFlags.NONE, 5000, None, self._on_registered)

    def _on_registered(self, bus, result):
        try:
            bus.call_finish(result)
        except GLib.Error as err:
            sys.stderr.write("trackai: tray host refused the icon ({}).\n".format(err.message))
            self._set_registered(False)
            return
        self._set_registered(True)

    def _on_watcher_vanished(self, _bus, _name):
        self._set_registered(False)

    def _set_registered(self, value):
        if value != self.registered:
            self.registered = value
            self.on_host_changed(value)

    # -- D-Bus handlers ----------------------------------------------------

    def _on_method_call(self, _bus, _sender, _path, _iface, method, params, invocation):
        if method in ("Activate", "SecondaryActivate", "ContextMenu"):
            x, y = params.unpack()
            invocation.return_value(None)
            # Reply first: some hosts block their UI until the call returns.
            GLib.idle_add(self._activate, x, y)
            return
        if method == "Scroll":
            invocation.return_value(None)
            return
        invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod",
                                     "No such method: " + method)

    def _activate(self, x, y):
        try:
            self.on_activate(x, y)
        except Exception as err:      # never let a UI error escape into GLib
            sys.stderr.write("trackai: tray activation failed: {}\n".format(err))
        return False

    def _on_get_property(self, _bus, _sender, _path, _iface, name):
        if name not in _TYPES:
            return None
        return GLib.Variant(_TYPES[name], self._values[name])

    # -- updates -----------------------------------------------------------

    def _emit(self, signal, params=None):
        if self._bus is None:
            return
        try:
            self._bus.emit_signal(None, ITEM_PATH, ITEM_IFACE, signal, params)
        except GLib.Error:
            pass

    def set_icon(self, pixmaps):
        """``pixmaps``: [(width, height, ARGB32 bytes in network order)]."""
        if pixmaps == self._values["IconPixmap"]:
            return
        self._values["IconPixmap"] = pixmaps
        self._emit("NewIcon")

    def set_label(self, label, guide=""):
        if self._values["XAyatanaLabel"] == label:
            return
        self._values["XAyatanaLabel"] = label
        self._values["XAyatanaLabelGuide"] = guide
        self._emit("XAyatanaNewLabel", GLib.Variant("(ss)", (label, guide)))
