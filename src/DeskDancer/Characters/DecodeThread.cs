using System.Collections.Concurrent;
using DeskDancer.Platform;

namespace DeskDancer.Characters;

/// <summary>
/// The one thread that decodes image packs behind the scenes.
///
/// It is a thread of its own, and only one, for the sake of memory. A decoder goes
/// through a few megabytes of scratch memory for every frame, and on Linux the C library
/// keeps a separate pool of freed memory for each thread that ever asked it for any. With
/// decoding spread over whichever threads were free, every one of them ended up sitting
/// on its own few megabytes for good. Kept to one thread, there is one such pool.
/// </summary>
public static class DecodeThread
{
    static readonly ConcurrentQueue<Action> Wanted = new(), Spare = new();
    static readonly SemaphoreSlim Queued = new(0);
    static int _started;

    /// <summary>
    /// Has the work done on the decoding thread. Work that something is waiting for goes
    /// ahead of <paramref name="spare"/> work, which is only done when nothing else is.
    /// </summary>
    public static Task<T> Run<T>(Func<T> work, bool spare = false)
    {
        // Whoever is waiting for the result carries on from a thread of their own, not this one.
        var done = new TaskCompletionSource<T>(TaskCreationOptions.RunContinuationsAsynchronously);
        (spare ? Spare : Wanted).Enqueue(() =>
        {
            try
            {
                done.SetResult(work());
            }
            catch (Exception ex)
            {
                done.SetException(ex);
            }
        });
        if (Interlocked.Exchange(ref _started, 1) == 0)
            new Thread(Work) { IsBackground = true, Name = "Decoding" }.Start();
        Queued.Release();
        return done.Task;
    }

    static void Work()
    {
        while (true)
        {
            Queued.Wait();
            if (Wanted.TryDequeue(out var work) || Spare.TryDequeue(out work)) work();
            // Decoding goes through far more memory than it ends up handing over. Once
            // there is nothing left to decode, the C library is asked to give that back.
            if (Wanted.IsEmpty && Spare.IsEmpty) FreedMemory.Return();
        }
    }
}
