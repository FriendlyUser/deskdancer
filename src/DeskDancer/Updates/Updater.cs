using System.Reflection;
using Avalonia.Threading;
using Velopack;
using Velopack.Sources;

namespace DeskDancer.Updates;

/// <summary>Where the updater has got to.</summary>
public enum UpdateState
{
    /// <summary>This copy cannot update itself: it was not put in by one of DeskDancer's own downloads.</summary>
    Unavailable,
    /// <summary>Nothing is going on: no look has been taken yet, or the last one found nothing newer.</summary>
    Idle,
    /// <summary>Asking whether there is a newer version.</summary>
    Checking,
    /// <summary>Fetching a newer version; <see cref="Updater.Progress"/> says how far it has got.</summary>
    Downloading,
    /// <summary>A newer version has been fetched, and goes in when the program restarts.</summary>
    Ready,
    /// <summary>The last look or download went wrong; <see cref="Updater.Problem"/> says how.</summary>
    Failed,
}

/// <summary>
/// Keeps the program up to date from its releases on GitHub, with Velopack
/// (https://velopack.io). A release made by the release workflow carries, for each system, the
/// package Velopack swaps in and a list saying which version it is. This looks at that list,
/// downloads a newer package if there is one, and hands over to Velopack's updater, which
/// waits for the program to close, puts the new version in its place and starts it again.
///
/// Only a copy that Velopack itself put there can do this: one installed by Setup.exe on
/// Windows, the AppImage on Linux, or the app from the Mac download. A copy built from source
/// or run with <c>dotnet run</c> is <see cref="UpdateState.Unavailable"/>, and says so.
///
/// Everything here that changes is changed on the UI thread, and <see cref="Changed"/> is
/// raised there, so a window can simply show what it finds.
/// </summary>
public sealed class Updater
{
    /// <summary>The repository whose releases the program updates itself from.</summary>
    public const string Repository = "https://github.com/FriendlyUser/deskdancer";

    /// <summary>The page a person can download the newest version from by hand.</summary>
    public const string DownloadPage = Repository + "/releases/latest";

    readonly UpdateManager? _manager;
    readonly string[] _restartArguments;
    VelopackAsset? _ready;
    int _busy;
    bool _restarting;

    /// <summary>
    /// <paramref name="feed"/> is a folder or web address to look for releases in, for trying
    /// updates out; null for the releases on GitHub. <paramref name="restartArguments"/> are
    /// handed to the new version when it is started, so it comes back as this one was run.
    /// </summary>
    public Updater(string? feed, string[] restartArguments)
    {
        _restartArguments = restartArguments;
        Feed = string.IsNullOrWhiteSpace(feed) ? null : feed;
        try
        {
            // Without a token GitHub answers 60 questions an hour from one address, which is
            // far more than this asks.
            _manager = Feed == null ? new UpdateManager(new GithubSource(Repository, null, false)) : new UpdateManager(Feed);
            if (_manager.IsInstalled)
            {
                // A version fetched last time that has not gone in yet.
                _ready = _manager.UpdatePendingRestart;
                NewVersion = _ready?.Version.ToString();
                State = _ready != null ? UpdateState.Ready : UpdateState.Idle;
            }
        }
        catch (Exception ex)
        {
            Log.Error("Updates are not available", ex);
            _manager = null;
        }
    }

    /// <summary>Where releases are looked for when it is not GitHub; null when it is.</summary>
    public string? Feed { get; }

    /// <summary>True for a copy that can update itself.</summary>
    public bool CanUpdate => _manager is { IsInstalled: true };

    /// <summary>The version this copy is: the release it was installed from, or else the one it was built as.</summary>
    public string Version => InstalledVersion(_manager);

    public UpdateState State { get; private set; } = UpdateState.Unavailable;

    /// <summary>The newer version that is being fetched or is ready to go in.</summary>
    public string? NewVersion { get; private set; }

    /// <summary>How much of the download is done, from 0 to 100.</summary>
    public int Progress { get; private set; }

    /// <summary>What went wrong the last time, in a line.</summary>
    public string? Problem { get; private set; }

    /// <summary>When releases were last looked at and an answer came back.</summary>
    public DateTime? LastChecked { get; private set; }

    /// <summary>Raised on the UI thread whenever any of the above has changed.</summary>
    public event Action? Changed;

    /// <summary>The version of the copy this program is, without starting anything up: for <c>--version</c>.</summary>
    public static string CurrentVersion()
    {
        try
        {
            return InstalledVersion(new UpdateManager(new GithubSource(Repository, null, false)));
        }
        catch (Exception)
        {
            return InstalledVersion(null);
        }
    }

    static string InstalledVersion(UpdateManager? manager) =>
        manager is { IsInstalled: true, CurrentVersion: { } installed } ? installed.ToString()
        : typeof(Updater).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion.Split('+')[0]
          ?? typeof(Updater).Assembly.GetName().Version?.ToString(3) ?? "unknown";

    /// <summary>
    /// Looks for a newer release and, if there is one, downloads it, leaving it
    /// <see cref="UpdateState.Ready"/> to go in. It does nothing in a copy that cannot update
    /// itself, or while a look is already under way, and it never throws: what goes wrong is
    /// logged and left in <see cref="Problem"/>.
    /// </summary>
    public async Task CheckAsync()
    {
        if (_manager is not { IsInstalled: true } manager || _restarting) return;
        if (Interlocked.Exchange(ref _busy, 1) == 1) return;
        try
        {
            await Show(() => (State, Problem) = (UpdateState.Checking, null));
            // Off the UI thread: the mates must not stop moving while GitHub is asked.
            var found = await Task.Run(manager.CheckForUpdatesAsync);
            if (found == null)
            {
                await Show(() => (State, LastChecked) = (_ready != null ? UpdateState.Ready : UpdateState.Idle, DateTime.Now));
                return;
            }
            string version = found.TargetFullRelease.Version.ToString();
            await Show(() => (State, NewVersion, Progress, LastChecked) = (UpdateState.Downloading, version, 0, DateTime.Now));
            int shown = 0;
            await Task.Run(() => manager.DownloadUpdatesAsync(found, percent =>
            {
                // Told about every step of the way; shown every few.
                if (percent < shown + 4 && percent < 100) return;
                shown = percent;
                Dispatcher.UIThread.Post(() =>
                {
                    if (State != UpdateState.Downloading) return;
                    Progress = percent;
                    Changed?.Invoke();
                });
            }));
            await Show(() =>
            {
                _ready = found.TargetFullRelease;
                (State, Progress) = (UpdateState.Ready, 100);
            });
        }
        catch (Exception ex)
        {
            Log.Error("Could not update", ex);
            await Show(() => (State, Problem) = (UpdateState.Failed, ex.Message.ReplaceLineEndings(" ").Trim()));
        }
        finally
        {
            Interlocked.Exchange(ref _busy, 0);
        }
    }

    /// <summary>
    /// Starts Velopack's updater, which waits for this program to close, puts the downloaded
    /// version in its place and starts it. Returns true if it is now waiting: the program
    /// should then close, within a minute. False if there is nothing to put in or it could
    /// not be started, which leaves everything as it was.
    /// </summary>
    public bool BeginRestart()
    {
        if (_manager == null || _ready == null || _restarting) return false;
        try
        {
            // Silent: no window of Velopack's own while it works. The mates are gone for a moment and come back.
            _manager.WaitExitThenApplyUpdates(_ready, silent: true, restart: true, _restartArguments);
            _restarting = true;
            return true;
        }
        catch (Exception ex)
        {
            Log.Error("Could not start the update", ex);
            (State, Problem) = (UpdateState.Failed, ex.Message.ReplaceLineEndings(" ").Trim());
            Changed?.Invoke();
            return false;
        }
    }

    /// <summary>Makes a change on the UI thread and tells whoever is watching.</summary>
    Task Show(Action change) => Dispatcher.UIThread.InvokeAsync(() =>
    {
        change();
        Changed?.Invoke();
    }).GetTask();
}
