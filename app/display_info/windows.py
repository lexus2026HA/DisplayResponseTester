import ctypes as c
import sys

U = c.c_uint32
I = c.c_int32

def fields(**definitions):
    return list(definitions.items())

class Luid(c.Structure):
    _fields_ = fields(low=U, high=I)

class Ratio(c.Structure):
    _fields_ = fields(n=U, d=U)

    def value(self):
        return self.n / self.d if self.d else None

class Size(c.Structure):
    _fields_ = fields(w=U, h=U)

class Signal(c.Structure):
    _fields_ = fields(clock=c.c_uint64, horizontal=Ratio, vertical=Ratio,
                      active=Size, total=Size, standard=U, scan=U)

class Mode(c.Structure):
    _fields_ = fields(kind=U, id=U, adapter=Luid, signal=Signal)

class Source(c.Structure):
    _fields_ = fields(adapter=Luid, id=U, index=U, flags=U)

class Target(c.Structure):
    _fields_ = fields(adapter=Luid, id=U, index=U, output=U, rotation=U,
                      scaling=U, rate=Ratio, scan=U, available=I, flags=U)

class Path(c.Structure):
    _fields_ = fields(source=Source, target=Target, flags=U)

class Header(c.Structure):
    _fields_ = fields(kind=U, size=U, adapter=Luid, id=U)

class SourceName(c.Structure):
    _fields_ = fields(header=Header, name=c.c_wchar * 32)

class TargetName(c.Structure):
    _fields_ = fields(header=Header, flags=U, output=U, vendor=c.c_uint16,
                      product=c.c_uint16, connector=U, name=c.c_wchar * 64,
                      path=c.c_wchar * 128)

class AdapterName(c.Structure):
    _fields_ = fields(header=Header, path=c.c_wchar * 128)

class Color(c.Structure):
    _fields_ = fields(header=Header, flags=U, encoding=U, bits=U, mode=U)

class DevMode(c.Structure):
    _fields_ = fields(name=c.c_wchar * 32, spec=c.c_uint16, driver=c.c_uint16,
                      size=c.c_uint16, extra=c.c_uint16, flags=U, display=c.c_byte * 16,
                      printer=c.c_int16 * 5, form=c.c_wchar * 32, logpixels=c.c_uint16,
                      bits=U, width=U, height=U, display_flags=U, hz=U, reserved=U * 8)

OUTPUTS = {0: "VGA", 4: "DVI", 5: "HDMI", 6: "LVDS", 10: "DisplayPort",
           11: "Embedded DisplayPort", 15: "Miracast", 16: "Indirect wired",
           17: "Virtual", 18: "DisplayPort USB tunnel", 0x80000000: "Internal"}

def request(api, structure, kind, endpoint):
    info = structure()
    info.header = Header(kind, c.sizeof(info), endpoint.adapter, endpoint.id)
    return info if api.DisplayConfigGetDeviceInfo(c.byref(info)) == 0 else None

def gdi_modes(api, name):
    modes = set()
    index = 0
    while True:
        item = DevMode()
        item.size = c.sizeof(item)
        if not api.EnumDisplaySettingsW(name, index, c.byref(item)):
            break
        modes.add((item.width, item.height, item.hz if item.hz > 1 else None, item.bits))
        index += 1
    current = DevMode()
    current.size = c.sizeof(current)
    if not api.EnumDisplaySettingsW(name, -1, c.byref(current)):
        current = None
    return sorted(modes, key=lambda m: (m[0], m[1], m[2] or 0, m[3])), current

def active_paths(api):
    for _ in range(4):
        paths, modes = U(), U()
        if api.GetDisplayConfigBufferSizes(2, c.byref(paths), c.byref(modes)):
            break
        path_data, mode_data = (Path * paths.value)(), (Mode * modes.value)()
        result = api.QueryDisplayConfig(2, c.byref(paths), path_data,
                                        c.byref(modes), mode_data, None)
        if result == 0:
            return path_data[:paths.value], mode_data[:modes.value]
        if result != 122:
            break
    return [], []

def edid_bytes(device_path):
    import winreg
    parts = device_path.removeprefix("\\\\?\\").split("#")
    if len(parts) < 3 or parts[0].upper() != "DISPLAY":
        return b""
    key = "\\".join(("SYSTEM\\CurrentControlSet\\Enum", *parts[:3], "Device Parameters"))
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
            return winreg.QueryValueEx(handle, "EDID")[0]
    except OSError:
        return b""

def adapter_driver(device_path):
    import winreg
    parts = device_path.removeprefix("\\\\?\\").split("#")
    if len(parts) < 3:
        return None, None
    device = "\\".join(("SYSTEM\\CurrentControlSet\\Enum", *parts[:3]))
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, device) as handle:
            driver = winreg.QueryValueEx(handle, "Driver")[0]
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            "SYSTEM\\CurrentControlSet\\Control\\Class\\" + driver) as handle:
            return (winreg.QueryValueEx(handle, "DriverDesc")[0],
                    winreg.QueryValueEx(handle, "DriverVersion")[0])
    except OSError:
        return None, None

def read_windows():
    if sys.platform != "win32":
        return []
    api = c.windll.user32
    paths, modes = active_paths(api)
    records = []
    for path in paths:
        source = request(api, SourceName, 1, path.source)
        if not source:
            continue
        target = path.target
        name = request(api, TargetName, 2, target)
        adapter = request(api, AdapterName, 4, target)
        gpu, driver = adapter_driver(adapter.path) if adapter else (None, None)
        color2 = request(api, Color, 15, target)
        color = color2 or request(api, Color, 9, target)
        possible, current = gdi_modes(api, source.name)
        signal = modes[target.index].signal if target.index < len(modes) and modes[target.index].kind == 2 else None
        device = name.path if name else ""
        hdr_supported = bool(color2.flags & 16) if color2 else None
        hdr_mode = {0: "SDR", 1: "WCG", 2: "HDR"}.get(color2.mode) if color2 else None
        records.append(dict(
            screen=source.name, id=device or source.name, name=name.name if name else "",
            edid=edid_bytes(device), gpu=gpu, driver=driver,
            connection=OUTPUTS.get(target.output), hz=target.rate.value() or
            (current.hz if current and current.hz > 1 else None),
            desktop=[current.width, current.height] if current else None, modes=possible,
            origin=list((I*2).from_buffer_copy(current.display)) if current else None,
            active=[signal.active.w, signal.active.h] if signal else None,
            total=[signal.total.w, signal.total.h] if signal else None,
            signal_hz=signal.vertical.value() if signal else None,
            horizontal_hz=signal.horizontal.value() if signal else None,
            pixel_clock=signal.clock if signal and signal.clock else None,
            bits=color.bits if color and color.bits else None,
            encoding={0:"RGB",1:"YCbCr 4:4:4",2:"YCbCr 4:2:2",3:"YCbCr 4:2:0",4:"Intensity"}.get(color.encoding) if color else None,
            hdr_supported=hdr_supported, hdr_mode=hdr_mode,
            hdr_enabled=bool(color2.flags & 32) if color2 else None,
        ))
    return records
