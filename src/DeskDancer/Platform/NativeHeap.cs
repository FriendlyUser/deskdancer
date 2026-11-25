using System.Runtime.InteropServices;

namespace DeskDancer.Platform;

/// <summary>
/// Hands memory that has been freed back to the system.
///
/// Decoding a clip takes room for its frames twice for a moment: as decoded, and as the
/// trimmed copies that are kept. The first set is freed straight away, but the C library on
/// Linux holds on to freed memory of this size for reuse unless it is asked to let go, so
/// the process would stay as large as its busiest moment. One call after each load fixes
/// that. Windows gives blocks of this size back on its own, so there this does nothing.
/// </summary>
public static class NativeHeap
{
    static volatile bool _unavailable;

    public static void Trim()
    {
        if (_unavailable || !OperatingSystem.IsLinux()) return;
        try
        {
            malloc_trim(0);
        }
        catch (Exception ex) when (ex is DllNotFoundException or EntryPointNotFoundException)
        {
            // A C library other than glibc (musl, say): it has no such call, and needs none.
            _unavailable = true;
        }
    }

    [DllImport("libc.so.6")]
    static extern int malloc_trim(nuint pad);
}
