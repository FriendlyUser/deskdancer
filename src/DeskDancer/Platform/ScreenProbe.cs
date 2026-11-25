using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using Avalonia;
using Avalonia.Media;
using Avalonia.Platform;
using SkiaSharp;

namespace DeskDancer.Platform;

/// <summary>
/// Reads pixels back off the real screen. The smoke test uses it to check that the mate is
/// visible and that the rest of its window really is see-through.
///
/// Windows: straight off the screen, a pixel at a time.
/// macOS: out of a screenshot taken with the system's own tool. Screenshots there need
/// screen recording to be allowed for whatever started the program, and the system asks
/// the user when it is not, so none is taken unless <see cref="UseScreenshots"/> is on.
/// </summary>
public static class ScreenProbe
{
    [DllImport("user32.dll")]
    static extern IntPtr GetDC(IntPtr hWnd);

    [DllImport("user32.dll")]
    static extern int ReleaseDC(IntPtr hWnd, IntPtr hdc);

    [DllImport("gdi32.dll")]
    static extern uint GetPixel(IntPtr hdc, int x, int y);

    /// <summary>macOS: whether screenshots may be taken. Off unless asked for.</summary>
    public static bool UseScreenshots { get; set; }

    public static bool Supported => OperatingSystem.IsWindows() || OperatingSystem.IsMacOS() && UseScreenshots;

    // macOS: the latest screenshot, and how many of its pixels there are to one of the screen's.
    static SKBitmap? _shot;
    static double _shotScale = 1;

    /// <summary>
    /// Has a fresh look at the screen, for <see cref="PixelAt"/> to read from. On Windows
    /// there is nothing to do. On macOS this takes a screenshot of the main display and
    /// leaves it at <paramref name="savedAs"/>. Returns what went wrong, or null.
    /// </summary>
    public static string? Look(Screen mainScreen, string savedAs)
    {
        if (!Supported) return "the screen cannot be read here";
        if (!OperatingSystem.IsMacOS()) return null;
        try
        {
            // An old picture of the same name must not be mistaken for a new one.
            File.Delete(savedAs);
            // -x: without the camera sound. -m: the main display only.
            var start = new ProcessStartInfo("/usr/sbin/screencapture") { UseShellExecute = false };
            foreach (string argument in (string[])["-x", "-m", "-t", "png", savedAs]) start.ArgumentList.Add(argument);
            using var tool = Process.Start(start);
            if (tool == null) return "screencapture did not start";
            if (!tool.WaitForExit(20000))
            {
                tool.Kill();
                return "screencapture did not finish";
            }
            if (tool.ExitCode != 0) return $"screencapture failed with exit code {tool.ExitCode}";
            var shot = SKBitmap.Decode(savedAs);
            if (shot == null) return "the screenshot could not be read";
            _shot?.Dispose();
            _shot = shot;
            _shotScale = shot.Width / (double)mainScreen.Bounds.Width;
            return null;
        }
        catch (Exception ex) when (ex is Win32Exception or IOException or InvalidOperationException or UnauthorizedAccessException)
        {
            return "screencapture could not be run: " + ex.Message;
        }
    }

    /// <summary>The colour shown at a screen position, or null if it cannot be read.</summary>
    public static Color? PixelAt(PixelPoint point)
    {
        if (!Supported) return null;
        if (OperatingSystem.IsMacOS())
        {
            if (_shot == null) return null;
            int x = (int)(point.X * _shotScale), y = (int)(point.Y * _shotScale);
            if (x < 0 || y < 0 || x >= _shot.Width || y >= _shot.Height) return null;
            var colour = _shot.GetPixel(x, y);
            return Color.FromRgb(colour.Red, colour.Green, colour.Blue);
        }
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
