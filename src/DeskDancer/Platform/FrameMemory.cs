using System.Runtime.InteropServices;

namespace DeskDancer.Platform;

/// <summary>
/// Memory for reading an image pack: the bytes of each file while it is decoded, and the
/// frames that come out of it until they have been drawn. Tens of megabytes at a time,
/// wanted for a while and then not at all.
///
/// Linux: the C library keeps what a program frees, to hand out again later, and how
/// much of it <see cref="FreedMemory"/> can get it to give back depends on what else the
/// program has been doing. So none of this is taken from the C library. It is mapped
/// straight from the system and unmapped when it is finished with.
/// Anywhere else this is ordinary allocation: Windows and macOS return blocks of this
/// size by themselves.
/// </summary>
public static unsafe class FrameMemory
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

    static bool _cannotMap = !OperatingSystem.IsLinux();

    /// <summary>Takes a block of zeroed memory.</summary>
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

    [DllImport("libc")]
    static extern nint mmap(nint address, nuint length, int protection, int flags, int file, nint offset);

    [DllImport("libc")]
    static extern int munmap(nint address, nuint length);
}
