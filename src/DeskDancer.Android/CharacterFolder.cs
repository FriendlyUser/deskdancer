using Android.App;
using Android.Content;
using Android.Provider;
using DeskDancer.Characters;
using AUri = Android.Net.Uri;

namespace DeskDancer.Droid;

/// <summary>
/// The folder on the phone where the user keeps characters of their own, chosen in Android's
/// folder picker. Android lets an app read such a folder only through the picker's grant, not
/// as ordinary files, while the pack loader reads ordinary files. So the characters in it are
/// copied into the app's own storage (the library's user folder), and copied again whenever
/// they change: only files that are new or different are read, and characters or files gone
/// from the folder go from the copy too.
///
/// Laid out as on a computer, each folder in it is one character. A folder with pictures or
/// a character.json directly in it is taken as one character on its own.
/// </summary>
public static class CharacterFolder
{
    const string ExternalStorage = "com.android.externalstorage.documents";
    const long MaxFileBytes = 64L * 1024 * 1024;
    static readonly string[] PackFiles = [".png", ".gif", ".webp", ".jpg", ".jpeg", ".bmp", ".json"];
    static readonly SemaphoreSlim OneAtATime = new(1, 1);

    /// <summary>Where the copies live: the folder the library scans for the user's own characters.</summary>
    public static string Copies => CharacterLibrary.UserFolder;

    /// <summary>The picker, opened on <paramref name="startAt"/> if given.</summary>
    public static Intent PickerIntent(AUri? startAt)
    {
        var intent = new Intent(Intent.ActionOpenDocumentTree);
        intent.AddFlags(ActivityFlags.GrantReadUriPermission | ActivityFlags.GrantPersistableUriPermission);
        if (startAt != null) intent.PutExtra(DocumentsContract.ExtraInitialUri, startAt);
        return intent;
    }

    /// <summary>A folder on the phone's own storage, such as "Documents/DeskDancer", as the picker names it.</summary>
    public static AUri OnPhone(string path) =>
        DocumentsContract.BuildDocumentUri(ExternalStorage, "primary:" + path.Trim('/'))!;

    /// <summary>Keeps the picker's grant, so the folder can still be read after the phone restarts.</summary>
    public static void Remember(Context context, AUri tree, ActivityFlags granted)
    {
        var keep = granted & (ActivityFlags.GrantReadUriPermission | ActivityFlags.GrantWriteUriPermission);
        if (!keep.HasFlag(ActivityFlags.GrantReadUriPermission)) keep |= ActivityFlags.GrantReadUriPermission;
        if (Stage.CharactersFolder is { } old && old != tree.ToString()) Release(context, AUri.Parse(old)!);
        context.ContentResolver!.TakePersistableUriPermission(tree, keep);
        Stage.CharactersFolder = tree.ToString();
    }

    /// <summary>Stops using the folder: gives up the grant and removes the copies.</summary>
    public static void Forget(Context context)
    {
        if (Stage.CharactersFolder is { } old) Release(context, AUri.Parse(old)!);
        Stage.CharactersFolder = null;
        try
        {
            if (Directory.Exists(Copies)) Directory.Delete(Copies, recursive: true);
        }
        catch (Exception ex)
        {
            Log.Error("Could not remove the copied characters", ex);
        }
    }

    static void Release(Context context, AUri tree)
    {
        try
        {
            context.ContentResolver!.ReleasePersistableUriPermission(tree,
                ActivityFlags.GrantReadUriPermission | ActivityFlags.GrantWriteUriPermission);
        }
        catch (Exception)
        {
            // Not held, or only in part: nothing to give up.
        }
    }

    /// <summary>The chosen folder, if there is one and the app may still read it.</summary>
    public static AUri? Chosen(Context context, out bool lostAccess)
    {
        lostAccess = false;
        if (Stage.CharactersFolder is not { } text) return null;
        var tree = AUri.Parse(text)!;
        lostAccess = !(context.ContentResolver!.PersistedUriPermissions?.Any(p => p.IsReadPermission && p.Uri?.ToString() == text) ?? false);
        return tree;
    }

    /// <summary>A name for the folder a person recognises, like "Documents/DeskDancer on the phone".</summary>
    public static string Describe(Context context, AUri tree)
    {
        string id = DocumentsContract.GetTreeDocumentId(tree) ?? "";
        if (tree.Authority == ExternalStorage && id.IndexOf(':') is int colon and > 0)
        {
            string volume = id[..colon], path = id[(colon + 1)..];
            string where = volume == "primary" ? "on the phone" : "on the SD card";
            return path.Length == 0 ? $"the top of the storage {where}" : $"{path} {where}";
        }
        return DisplayName(context, tree, id) ?? id;
    }

    /// <summary>Opens the folder in the phone's Files app. False if nothing on the phone could.</summary>
    public static bool Open(Activity activity, AUri tree)
    {
        var folder = DocumentsContract.BuildDocumentUriUsingTree(tree, DocumentsContract.GetTreeDocumentId(tree))!;
        var view = new Intent(Intent.ActionView);
        view.SetDataAndType(folder, DocumentsContract.Document.MimeTypeDir);
        view.AddFlags(ActivityFlags.GrantReadUriPermission);
        try
        {
            activity.StartActivity(view);
            return true;
        }
        catch (ActivityNotFoundException)
        {
            return false;
        }
    }

    public sealed record Result(IReadOnlyList<string> Characters, int Copied, int Removed, string? Problem)
    {
        public bool Changed => Copied > 0 || Removed > 0;
    }

    /// <summary>
    /// Brings the copies up to date with the folder. Slow work: call it off the main thread.
    /// Returns null if a sync is already going.
    /// </summary>
    public static Result? Sync(Context context, AUri tree)
    {
        if (!OneAtATime.Wait(0)) return null;
        try
        {
            var resolver = context.ContentResolver!;
            string rootId = DocumentsContract.GetTreeDocumentId(tree)!;
            var top = List(resolver, tree, rootId);
            var counts = new Counts();

            // One character in the folder itself, or one in each folder inside it.
            bool single = top.Any(e => !e.IsDir && IsPackFile(e.Name));
            var packs = single
                ? new List<Entry> { new(rootId, Safe(DisplayName(context, tree, rootId) ?? "my-character"), true, 0, 0) }
                : top.Where(e => e.IsDir && !Skipped(e.Name)).ToList();

            Directory.CreateDirectory(Copies);
            var names = packs.Select(p => Safe(p.Name)).ToHashSet(StringComparer.OrdinalIgnoreCase);
            foreach (string dir in Directory.GetDirectories(Copies))
            {
                if (names.Contains(Path.GetFileName(dir))) continue;
                Directory.Delete(dir, recursive: true);
                counts.Removed++;
            }
            foreach (var pack in packs)
                Mirror(resolver, tree, pack.Id, Path.Combine(Copies, Safe(pack.Name)), counts);

            return new Result(packs.Select(p => Safe(p.Name)).ToList(), counts.Copied, counts.Removed, counts.Problem);
        }
        catch (Exception ex)
        {
            Log.Error("Could not read the characters folder", ex);
            return new Result([], 0, 0, ex.Message);
        }
        finally
        {
            OneAtATime.Release();
        }
    }

    sealed class Counts
    {
        public int Copied, Removed;
        public string? Problem;
    }

    sealed record Entry(string Id, string Name, bool IsDir, long Size, long Modified);

    static bool Skipped(string name) => name.StartsWith('.') || name.StartsWith('_');

    static bool IsPackFile(string name) => PackFiles.Contains(Path.GetExtension(name).ToLowerInvariant());

    static string Safe(string name)
    {
        foreach (char c in Path.GetInvalidFileNameChars()) name = name.Replace(c, '_');
        return name.Trim() is { Length: > 0 } trimmed ? trimmed : "_";
    }

    static void Mirror(ContentResolver resolver, AUri tree, string docId, string target, Counts counts)
    {
        Directory.CreateDirectory(target);
        var keep = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in List(resolver, tree, docId))
        {
            // Working files ("_source") and hidden ones are never read by the app, so not copied.
            if (Skipped(entry.Name)) continue;
            string path = Path.Combine(target, Safe(entry.Name));
            keep.Add(Path.GetFileName(path));
            if (entry.IsDir)
            {
                Mirror(resolver, tree, entry.Id, path, counts);
                continue;
            }
            if (entry.Size > MaxFileBytes)
            {
                counts.Problem ??= $"{entry.Name} is too big to use";
                continue;
            }
            var modified = entry.Modified > 0 ? DateTimeOffset.FromUnixTimeMilliseconds(entry.Modified).UtcDateTime : (DateTime?)null;
            if (File.Exists(path) && new FileInfo(path).Length == entry.Size
                && (modified == null || File.GetLastWriteTimeUtc(path) == modified)) continue;
            string part = path + ".part";
            using (var input = resolver.OpenInputStream(DocumentsContract.BuildDocumentUriUsingTree(tree, entry.Id)!)
                               ?? throw new IOException($"Could not open {entry.Name}"))
            using (var output = File.Create(part))
                input.CopyTo(output);
            File.Move(part, path, overwrite: true);
            if (modified != null) File.SetLastWriteTimeUtc(path, modified.Value);
            counts.Copied++;
        }
        foreach (string file in Directory.GetFiles(target))
        {
            if (keep.Contains(Path.GetFileName(file))) continue;
            File.Delete(file);
            counts.Removed++;
        }
        foreach (string dir in Directory.GetDirectories(target))
        {
            if (keep.Contains(Path.GetFileName(dir))) continue;
            Directory.Delete(dir, recursive: true);
            counts.Removed++;
        }
    }

    static List<Entry> List(ContentResolver resolver, AUri tree, string docId)
    {
        var list = new List<Entry>();
        var children = DocumentsContract.BuildChildDocumentsUriUsingTree(tree, docId)!;
        string[] columns =
        [
            DocumentsContract.Document.ColumnDocumentId, DocumentsContract.Document.ColumnDisplayName,
            DocumentsContract.Document.ColumnMimeType, DocumentsContract.Document.ColumnSize,
            DocumentsContract.Document.ColumnLastModified,
        ];
        using var cursor = resolver.Query(children, columns, null, null, null);
        while (cursor != null && cursor.MoveToNext())
        {
            string? id = cursor.GetString(0), name = cursor.GetString(1);
            if (id == null || name == null) continue;
            bool isDir = cursor.GetString(2) == DocumentsContract.Document.MimeTypeDir;
            long size = cursor.IsNull(3) ? 0 : cursor.GetLong(3);
            long modified = cursor.IsNull(4) ? 0 : cursor.GetLong(4);
            list.Add(new Entry(id, name, isDir, size, modified));
        }
        return list;
    }

    static string? DisplayName(Context context, AUri tree, string docId)
    {
        try
        {
            var doc = DocumentsContract.BuildDocumentUriUsingTree(tree, docId)!;
            using var cursor = context.ContentResolver!.Query(doc, [DocumentsContract.Document.ColumnDisplayName], null, null, null);
            return cursor != null && cursor.MoveToFirst() ? cursor.GetString(0) : null;
        }
        catch (Exception)
        {
            return null;
        }
    }
}
