using Android.Content;
using Android.Content.PM;
using Android.Content.Res;

namespace DeskDancer.Droid;

/// <summary>
/// The character packs ship inside the APK as assets, but the pack loader reads ordinary
/// files. They are copied into the app's own storage the first time the app starts, and
/// again whenever the app is updated.
/// </summary>
public static class CharacterAssets
{
    public static string Unpack(Context context)
    {
        string root = Path.Combine(context.FilesDir!.AbsolutePath, "characters");
        string stampFile = Path.Combine(root, ".installed");
        string stamp = InstalledAt(context);
        try
        {
            if (File.Exists(stampFile) && File.ReadAllText(stampFile) == stamp) return root;
            if (Directory.Exists(root)) Directory.Delete(root, recursive: true);
            Copy(context.Assets!, "characters", root);
            File.WriteAllText(stampFile, stamp);
        }
        catch (Exception ex)
        {
            Log.Error("Could not unpack the characters", ex);
        }
        return root;
    }

    static string InstalledAt(Context context)
    {
#pragma warning disable CA1422 // the int overload is the one every supported version has
        var info = context.PackageManager!.GetPackageInfo(context.PackageName!, (PackageInfoFlags)0);
#pragma warning restore CA1422
        return info?.LastUpdateTime.ToString() ?? "0";
    }

    static void Copy(AssetManager assets, string path, string target)
    {
        string[] children = assets.List(path) ?? [];
        if (children.Length == 0)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            using var input = assets.Open(path);
            using var output = File.Create(target);
            input.CopyTo(output);
            return;
        }
        foreach (string child in children)
            Copy(assets, path + "/" + child, Path.Combine(target, child));
    }
}
