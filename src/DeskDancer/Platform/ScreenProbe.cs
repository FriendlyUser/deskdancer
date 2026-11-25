using System.Runtime.InteropServices;
using Avalonia;
using Avalonia.Media;

namespace DeskDancer.Platform;

/// <summary>
/// Reads pixels back off the real screen. Windows only; the smoke test uses it to check
/// that the mate is visible and that the rest of its window really is see-through.
/// </summary>
public static class ScreenProbe
{
    [DllImport("user32.dll")]
    static extern IntPtr GetDC(IntPtr hWnd);

    [DllImport("user32.dll")]
    static extern int ReleaseDC(IntPtr hWnd, IntPtr hdc);

    [DllImport("gdi32.dll")]
    static extern uint GetPixel(IntPtr hdc, int x, int y);

    public static bool Supported => OperatingSystem.IsWindows();

    /// <summary>The colour shown at a screen position, or null if it cannot be read.</summary>
    public static Color? PixelAt(PixelPoint point)
    {
        if (!Supported) return null;
        IntPtr screen = GetDC(IntPtr.Zero);
        if (screen == IntPtr.Zero) return null;
        try
        {
            uint bgr = GetPixel(screen, point.X, point.Y);
            if (bgr == 0xFFFFFFFF) return null; // CLR_INVALID: off-screen
            return Color.FromRgb((byte)(bgr & 0xFF), (byte)((bgr >> 8) & 0xFF), (byte)((bgr >> 16) & 0xFF));
        }
        finally
        {
            ReleaseDC(IntPtr.Zero, screen);
        }
    }

    public static bool Near(Color a, Color b, int tolerance = 24) =>
        Math.Abs(a.R - b.R) <= tolerance && Math.Abs(a.G - b.G) <= tolerance && Math.Abs(a.B - b.B) <= tolerance;
}
