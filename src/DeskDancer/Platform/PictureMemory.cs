using System.Runtime.InteropServices;

namespace DeskDancer.Platform;

/// <summary>
/// Memory for the frames of image packs: tens of megabytes that come and go as clips
/// are loaded and let go of again.
///
/// Linux: the C library keeps what a program frees, to hand out again later, and how
/// much of it ever goes back to the system depends on what else the program has been
/// doing. So a frame being decoded is not taken from the C library at all. It is mapped
/// straight from the system and unmapped when it is finished with. The bitmaps made from
/// the frames are allocated inside Avalonia, where there is no such choice, so after
/// freeing those the C library is asked to give the pages back.
/// Anywhere else this is ordinary allocation: Windows returns blocks of this size by itself.
/// </summary>
public static unsafe class PictureMemory
{
    /// <summary>A block of memory, all zeroes to begin with.</summary>
    public sealed class Block
    {
        readonly nuint _bytes;
        readonly bool _mapped;
        nint _address;

        internal Block(nint address, nuint bytes, bool mapped)
        {
            _address = address;
            _bytes = bytes;
            _mapped = mapped;
        }

        public nint Address => _address;

        /// <summary>Gives the memory back. Doing so twice is harmless.</summary>
        public void GiveBack()
        {
            nint address = Interlocked.Exchange(ref _address, 0);
            if (address == 0) return;
            if (_mapped) munmap(address, _bytes);
            else NativeMemory.Free((void*)address);
        }
    }

    // The same on every kind of processor .NET runs on under Linux.
    const int ProtRead = 1, ProtWrite = 2, MapPrivate = 2, MapAnonymous = 0x20;

    /// <summary>Smaller blocks than this are not worth a mapping of their own; the C library does well enough by them.</summary>
    const long MapFrom = 128 * 1024;

    /// <summary>Handing pages back is not worth asking for until this many bytes have been freed.</summary>
    const long Worthwhile = 1024 * 1024;

    static bool _cannotMap = !OperatingSystem.IsLinux();
    static bool _cannotTrim = !OperatingSystem.IsLinux();
    static long _freed;

    /// <summary>Takes a block of zeroed memory to decode a frame into.</summary>
    public static Block Take(long bytes)
    {
        if (!_cannotMap && bytes >= MapFrom)
        {
            try
            {
                nint address = mmap(0, (nuint)bytes, ProtRead | ProtWrite, MapPrivate | MapAnonymous, -1, 0);
                if (address != -1) return new Block(address, (nuint)bytes, mapped: true);
            }
            catch (Exception ex) when (ex is DllNotFoundException or EntryPointNotFoundException)
            {
                _cannotMap = true;
            }
        }
        return new Block((nint)NativeMemory.AllocZeroed((nuint)bytes), (nuint)bytes, mapped: false);
    }

    /// <summary>Notes that this many bytes of bitmaps have just been freed.</summary>
    public static void Freed(long bytes)
    {
        if (!_cannotTrim) Interlocked.Add(ref _freed, bytes);
    }

    /// <summary>Has the pages of bitmaps freed since the last call handed back, once they add up to enough to matter.</summary>
    public static void Return()
    {
        if (_cannotTrim || Interlocked.Read(ref _freed) < Worthwhile) return;
        Interlocked.Exchange(ref _freed, 0);
        try
        {
            malloc_trim(0);
        }
        catch (Exception ex) when (ex is DllNotFoundException or EntryPointNotFoundException)
        {
            // A C library without this call, such as musl: carry on without it.
            _cannotTrim = true;
        }
    }

    [DllImport("libc")]
    static extern nint mmap(nint address, nuint length, int protection, int flags, int file, nint offset);

    [DllImport("libc")]
    static extern int munmap(nint address, nuint length);

    [DllImport("libc")]
    static extern int malloc_trim(nuint pad);
}
