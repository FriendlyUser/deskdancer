using System.Runtime.InteropServices;
using Avalonia;
using Avalonia.Controls;

namespace DeskDancer.Platform;

/// <summary>
/// Lets mouse clicks fall through the empty part of a mate's window to whatever is
/// underneath. A transparent window still swallows clicks across its whole rectangle,
/// so the window is told which rectangle actually holds the character.
///
/// Windows: a window region. This also clips drawing, so callers only shrink it while
/// nothing is being drawn outside the rectangle.
/// Linux (X11): an input shape, which affects mouse input only.
/// Anywhere else this does nothing and the whole window stays clickable.
/// </summary>
public static class ClickThrough
{
    static bool _failed;
    static IntPtr _display;

    /// <summary>True where shrinking the clickable area also hides whatever is drawn outside it.</summary>
    public static bool ClipsDrawing => OperatingSystem.IsWindows();

    public static bool Supported => !_failed && (OperatingSystem.IsWindows() || OperatingSystem.IsLinux());

    /// <summary>
    /// Makes only <paramref name="solid"/> (in window pixels) receive the mouse, or the whole
    /// window when it is null. Returns false if the platform could not do it.
    /// </summary>
    public static bool Apply(Window window, PixelRect? solid)
    {
        if (!Supported) return false;
        var handle = window.TryGetPlatformHandle();
        if (handle == null || handle.Handle == IntPtr.Zero) return false;

        try
        {
            if (OperatingSystem.IsWindows() && handle.HandleDescriptor == "HWND")
            {
                ApplyWindows(handle.Handle, solid);
                return true;
            }
            if (OperatingSystem.IsLinux() && handle.HandleDescriptor == "XID")
            {
                return ApplyX11(handle.Handle, solid);
            }
        }
        catch (Exception ex) when (ex is DllNotFoundException or EntryPointNotFoundException or BadImageFormatException)
        {
            // Missing libXext or similar: carry on with a fully clickable window.
            _failed = true;
            Log.Error("Click-through is not available on this system", ex);
        }
        return false;
    }

    // ---- Windows ----

    [DllImport("user32.dll", SetLastError = true)]
    static extern int SetWindowRgn(IntPtr hWnd, IntPtr hRgn, [MarshalAs(UnmanagedType.Bool)] bool redraw);

    [DllImport("gdi32.dll")]
    static extern IntPtr CreateRectRgn(int left, int top, int right, int bottom);

    [DllImport("gdi32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool DeleteObject(IntPtr obj);

    [DllImport("user32.dll")]
    static extern IntPtr WindowFromPoint(NativePoint point);

    [DllImport("user32.dll")]
    static extern IntPtr GetAncestor(IntPtr hWnd, uint flags);

    [StructLayout(LayoutKind.Sequential)]
    struct NativePoint
    {
        public int X, Y;
    }

    static void ApplyWindows(IntPtr hwnd, PixelRect? solid)
    {
        if (solid is not { } r)
        {
            SetWindowRgn(hwnd, IntPtr.Zero, true);
            return;
        }
        IntPtr region = CreateRectRgn(r.X, r.Y, r.Right, r.Bottom);
        // On success the system takes ownership of the region; only free it on failure.
        if (SetWindowRgn(hwnd, region, true) == 0) DeleteObject(region);
    }

    /// <summary>
    /// Windows only: whether the top-level window under a screen point is <paramref name="window"/>.
    /// Null on other systems. Used by the smoke test to prove click-through really works.
    /// </summary>
    public static bool? IsWindowAt(Window window, PixelPoint screenPoint)
    {
        if (!OperatingSystem.IsWindows()) return null;
        var handle = window.TryGetPlatformHandle();
        if (handle == null) return null;
        const uint root = 2; // GA_ROOT
        IntPtr hit = WindowFromPoint(new NativePoint { X = screenPoint.X, Y = screenPoint.Y });
        if (hit != IntPtr.Zero) hit = GetAncestor(hit, root);
        return hit == handle.Handle;
    }

    // ---- X11 ----

    const int ShapeInput = 2, ShapeSet = 0;

    [StructLayout(LayoutKind.Sequential)]
    struct XRectangle
    {
        public short X, Y;
        public ushort Width, Height;
    }

    [DllImport("libX11.so.6")]
    static extern IntPtr XOpenDisplay(IntPtr name);

    [DllImport("libX11.so.6")]
    static extern int XFlush(IntPtr display);

    [DllImport("libXext.so.6")]
    static extern int XShapeQueryExtension(IntPtr display, out int eventBase, out int errorBase);

    [DllImport("libXext.so.6")]
    static extern void XShapeCombineRectangles(IntPtr display, IntPtr window, int kind, int xOff, int yOff,
        [In] XRectangle[] rectangles, int count, int op, int ordering);

    [DllImport("libXext.so.6")]
    static extern void XShapeCombineMask(IntPtr display, IntPtr window, int kind, int xOff, int yOff, IntPtr mask, int op);

    static bool ApplyX11(IntPtr window, PixelRect? solid)
    {
        if (_display == IntPtr.Zero)
        {
            // A private connection: any client may set another window's shape.
            _display = XOpenDisplay(IntPtr.Zero);
            if (_display == IntPtr.Zero || XShapeQueryExtension(_display, out _, out _) == 0)
            {
                _failed = true;
                return false;
            }
        }

        if (solid is { } r)
        {
            XRectangle[] rect =
            [
                new()
                {
                    X = (short)Math.Clamp(r.X, short.MinValue, short.MaxValue),
                    Y = (short)Math.Clamp(r.Y, short.MinValue, short.MaxValue),
                    Width = (ushort)Math.Clamp(r.Width, 1, ushort.MaxValue),
                    Height = (ushort)Math.Clamp(r.Height, 1, ushort.MaxValue),
                },
            ];
            XShapeCombineRectangles(_display, window, ShapeInput, 0, 0, rect, 1, ShapeSet, 0);
        }
        else
        {
            // A "None" mask puts the default (whole window) input shape back.
            XShapeCombineMask(_display, window, ShapeInput, 0, 0, IntPtr.Zero, ShapeSet);
        }
        XFlush(_display);
        return true;
    }
}
