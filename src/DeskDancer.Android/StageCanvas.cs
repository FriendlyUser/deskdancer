using Android.Content;
using Android.Graphics;
using Avalonia;
using Avalonia.Media.Imaging;
using AView = Android.Views.View;
using ABitmap = Android.Graphics.Bitmap;
using APixelFormat = Avalonia.Platform.PixelFormat;

namespace DeskDancer.Droid;

/// <summary>
/// What the stage window shows: a plain Android view holding a picture of the mate, which
/// Avalonia draws off-screen each frame with the same renderer the desktop uses.
///
/// Avalonia's own Android view draws on a SurfaceView, and in an overlay Android composes
/// that surface as opaque, so the mate stood in a black box. An ordinary view in a
/// translucent window keeps its see-through pixels on every version of Android.
/// </summary>
public sealed class StageCanvas : AView
{
    readonly Vector _dpi;
    RenderTargetBitmap? _target;
    ABitmap? _picture;

    public StageCanvas(Context context, float density) : base(context)
    {
        _dpi = new Vector(96.0 * density, 96.0 * density);
    }

    /// <summary>Draws <paramref name="visual"/> into a picture of the given size in pixels and shows it.</summary>
    public void Render(Avalonia.Visual visual, int width, int height)
    {
        if (width <= 0 || height <= 0) return;
        if (_target == null || _picture == null || _target.PixelSize.Width != width || _target.PixelSize.Height != height)
        {
            _target?.Dispose();
            _picture?.Recycle();
            _picture?.Dispose();
            _target = new RenderTargetBitmap(new PixelSize(width, height), _dpi);
            _picture = ABitmap.CreateBitmap(width, height, ABitmap.Config.Argb8888!)!;
        }

        // Clears to transparent, then draws.
        _target.Render(visual);

        // Both are premultiplied, and Android's ARGB_8888 is laid out R, G, B, A in memory,
        // which is how Skia stores pixels on Android. Should Skia ever hand over B, G, R, A,
        // the two channels are swapped back.
        IntPtr pixels = _picture.LockPixels();
        try
        {
            int stride = _picture.RowBytes;
            _target.CopyPixels(new PixelRect(0, 0, width, height), pixels, stride * height, stride);
            if (_target.Format == APixelFormat.Bgra8888) SwapRedAndBlue(pixels, stride, width, height);
        }
        finally
        {
            _picture.UnlockPixels();
        }
        Invalidate();
    }

    static unsafe void SwapRedAndBlue(IntPtr pixels, int stride, int width, int height)
    {
        for (int y = 0; y < height; y++)
        {
            uint* row = (uint*)((byte*)pixels + (long)y * stride);
            for (int x = 0; x < width; x++)
            {
                uint p = row[x];
                row[x] = (p & 0xFF00FF00u) | ((p & 0x00FF0000u) >> 16) | ((p & 0x000000FFu) << 16);
            }
        }
    }

    protected override void OnDraw(Canvas canvas)
    {
        if (_picture != null) canvas.DrawBitmap(_picture, 0, 0, null);
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            _target?.Dispose();
            _target = null;
            _picture?.Recycle();
            _picture?.Dispose();
            _picture = null;
        }
        base.Dispose(disposing);
    }
}
