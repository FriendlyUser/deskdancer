using System.Runtime.InteropServices;

namespace DeskDancer.Platform;

/// <summary>
/// Hands memory the program has finished with back to the system.
///
/// Linux: the C library keeps freed memory to use again later, so after an image pack has
/// been decoded the program stays as large as it was at its fullest unless it is asked to
/// let go. This asks. It takes a millisecond or two.
/// Anywhere else this does nothing.
/// </summary>
public static class FreedMemory
{
    static bool _unavailable;

    [DllImport("libc", EntryPoint = "malloc_trim")]
    static extern int MallocTrim(nuint keep);

    public static void Return()
    {
        if (_unavailable || !OperatingSystem.IsLinux()) return;
        try
        {
            MallocTrim(0);
        }
        catch (Exception ex) when (ex is DllNotFoundException or EntryPointNotFoundException)
        {
            // A C library without this call, such as musl. There is nobody to ask.
            _unavailable = true;
        }
    }
}
