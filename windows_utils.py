def get_open_windows(exclude_title=""):
    windows = []
    try:
        import win32gui
        def cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                t = win32gui.GetWindowText(hwnd)
                if t and t != exclude_title:
                    windows.append((hwnd, t))
        win32gui.EnumWindows(cb, None)
    except Exception:
        pass
    return windows

def focus_window(hwnd):
    try:
        import win32gui, win32con
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass