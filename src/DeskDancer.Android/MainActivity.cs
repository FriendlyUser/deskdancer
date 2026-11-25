using Android;
using Android.App;
using Android.Content;
using Android.Content.PM;
using Android.OS;
using Android.Views;
using Android.Widget;
using DeskDancer.Engine;
using AUri = Android.Net.Uri;

namespace DeskDancer.Droid;

/// <summary>
/// The settings screen: permission, character, the folder of the user's own characters, the
/// moves to use, and buttons to put the mate on the screen, make it dance and put it away.
/// Long-pressing the mate brings this back.
///
/// Scripts can drive it too, which is how the CI test does:
/// <c>adb shell am start -n io.github.friendlyuser.deskdancer/.MainActivity --es command start|dance|rest|stop [--es character mochi]</c>
/// (<c>dance</c> starts or stops a dance; <c>rest</c> only stops one.)
/// After those the screen gets out of the way, so the mate is seen over whatever was there.
/// Adding <c>--ez calm true</c> keeps the mate from wandering off or dancing unasked, and
/// leaves the saved settings alone, so screenshots catch it where it was put.
/// <c>--es command reload</c> reads the characters folder again, and these leave the screen
/// up: <c>choose-folder [--es folder Documents/DeskDancer]</c> opens the folder picker there,
/// <c>open-folder</c> opens the chosen folder in the Files app, and
/// <c>show-moves [--es move backflip]</c> opens the list of moves and scrolls to one.
/// </summary>
[Activity(Name = "io.github.friendlyuser.deskdancer.MainActivity", Label = "DeskDancer",
          MainLauncher = true, Exported = true, LaunchMode = LaunchMode.SingleTask)]
public sealed class MainActivity : Activity
{
    const int PickFolderRequest = 1;

    ScrollView _scroll = null!;
    TextView _status = null!;
    Button _allow = null!;
    RadioGroup _characters = null!;
    readonly Dictionary<int, string> _characterIds = [];
    TextView _folderStatus = null!;
    Button _chooseFolder = null!, _openFolder = null!, _reloadFolder = null!, _forgetFolder = null!;
    Button _movesHeader = null!;
    LinearLayout _movesList = null!;
    readonly Dictionary<string, (CheckBox Box, bool BuiltIn)> _moveBoxes = [];
    // Set while boxes and buttons are being filled in, so that does not count as the user ticking them.
    bool _filling;

    protected override void OnCreate(Bundle? savedInstanceState)
    {
        base.OnCreate(savedInstanceState);
        Stage.EnsureReady(this);
        SetContentView(BuildUi());

        if (OperatingSystem.IsAndroidVersionAtLeast(33)
            && CheckSelfPermission(Manifest.Permission.PostNotifications) != Permission.Granted)
            RequestPermissions([Manifest.Permission.PostNotifications], 1);

        HandleCommand(Intent);
    }

    protected override void OnNewIntent(Intent? intent)
    {
        base.OnNewIntent(intent);
        HandleCommand(intent);
    }

    protected override void OnResume()
    {
        base.OnResume();
        Refresh();
        // Characters put in the folder since last time show up without asking.
        SyncFolder(announce: false);
    }

    bool CanDrawOverlays => Android.Provider.Settings.CanDrawOverlays(this);

    int Dp(double v) => (int)Math.Round(v * Resources!.DisplayMetrics!.Density);

    View BuildUi()
    {
        var column = new LinearLayout(this) { Orientation = Orientation.Vertical };
        column.SetPadding(Dp(24), Dp(32), Dp(24), Dp(24));

        TextView Text(string text, float size, ViewGroup? into = null)
        {
            var view = new TextView(this) { Text = text };
            view.SetTextSize(Android.Util.ComplexUnitType.Sp, size);
            view.SetPadding(0, Dp(8), 0, Dp(8));
            (into ?? column).AddView(view);
            return view;
        }
        Button Action(string text, Action onClick)
        {
            var button = new Button(this) { Text = text };
            button.Click += (_, _) => onClick();
            column.AddView(button);
            return button;
        }

        Text("DeskDancer", 28);
        _status = Text("", 16);
        _allow = Action("Allow display over other apps", () =>
            StartActivity(new Intent(Android.Provider.Settings.ActionManageOverlayPermission,
                Android.Net.Uri.Parse("package:" + PackageName))));

        Text("Character", 20);
        _characters = new RadioGroup(this);
        _characters.CheckedChange += (_, e) =>
        {
            if (_filling || !_characterIds.TryGetValue(e.CheckedId, out string? id)) return;
            Stage.CharacterId = id;
            if (MateService.Running) Send(MateService.ActionShow, id);
            FillMoves();
        };
        column.AddView(_characters);
        FillCharacters();

        Text("Your own characters", 20);
        Text("Keep characters of your own in a folder on the phone, one folder for each, laid out " +
             "as on a computer. DeskDancer copies them in from there, and again whenever you come " +
             "back to this screen.", 14);
        _folderStatus = Text("", 14);
        _chooseFolder = Action("Choose a folder", () => PickFolder(null));
        _openFolder = Action("Open the folder", OpenFolder);
        _reloadFolder = Action("Reload characters", () => SyncFolder(announce: true));
        _forgetFolder = Action("Stop using this folder", ForgetFolder);
        FillFolder();

        _movesHeader = Action("", () =>
        {
            _movesList.Visibility = _movesList.Visibility == ViewStates.Visible ? ViewStates.Gone : ViewStates.Visible;
            RefreshMoves();
        });
        _movesList = new LinearLayout(this) { Orientation = Orientation.Vertical, Visibility = ViewStates.Gone };
        column.AddView(_movesList);
        FillMoves();

        // Before Android 12 taps pass the mate whatever it looks like, so there is no choice to make.
        if (OperatingSystem.IsAndroidVersionAtLeast(31))
        {
            var solid = new CheckBox(this)
            {
                Text = "Solid mate: draw it at full strength. Taps right around it then stop " +
                       "reaching the app underneath, which Android allows only for see-through overlays.",
                Checked = Stage.Solid,
            };
            solid.CheckedChange += (_, e) =>
            {
                Stage.Solid = e.IsChecked;
                if (MateService.Running) Send(MateService.ActionShow);
            };
            column.AddView(solid);
        }

        Action("Put the mate on the screen", () => Start(null));
        Action("Dance", () => Send(MateService.ActionDance));
        Action("Put it away", Stop);
        Text("On the screen: drag the mate to carry and throw it, tap it to poke it, double-tap it to " +
             "start or stop a dance, and long-press it to come back here. The notification has " +
             "the same buttons.", 14);

        _scroll = new ScrollView(this) { FillViewport = true };
        _scroll.AddView(column);
        return _scroll;
    }

    void Refresh()
    {
        bool allowed = CanDrawOverlays;
        _allow.Visibility = allowed ? ViewStates.Gone : ViewStates.Visible;
        _status.Text = !allowed
            ? "First, let DeskDancer display over other apps. Android asks you to switch this on yourself."
            : MateService.Running ? "Your mate is on the screen." : "Ready. Put the mate on the screen below.";
    }

    // ---- Characters ----

    void FillCharacters()
    {
        _filling = true;
        _characters.RemoveAllViews();
        _characterIds.Clear();
        foreach (var info in Stage.Library.Available)
        {
            var radio = new RadioButton(this) { Text = info.Name, Id = View.GenerateViewId() };
            _characterIds[radio.Id] = info.Id;
            _characters.AddView(radio);
            if (info.Id.Equals(Stage.CharacterId, StringComparison.OrdinalIgnoreCase)) radio.Checked = true;
        }
        _filling = false;
    }

    // ---- The folder of the user's own characters ----

    void FillFolder(string? note = null)
    {
        var tree = CharacterFolder.Chosen(this, out bool lostAccess);
        bool chosen = tree != null;
        foreach (var button in new[] { _openFolder, _reloadFolder, _forgetFolder })
            button.Visibility = chosen ? ViewStates.Visible : ViewStates.Gone;
        _chooseFolder.Text = chosen ? "Choose another folder" : "Choose a folder";
        if (tree == null)
        {
            _folderStatus.Text = "No folder chosen yet.";
            return;
        }
        string where = CharacterFolder.Describe(this, tree);
        if (lostAccess)
        {
            _folderStatus.Text = $"DeskDancer may no longer read {where}. Choose it again.";
            return;
        }
        string copies = Path.GetFullPath(CharacterFolder.Copies);
        var mine = Stage.Library.Available
            .Where(c => c.Folder != null && Path.GetFullPath(c.Folder).StartsWith(copies, StringComparison.Ordinal))
            .Select(c => c.Name).ToList();
        _folderStatus.Text = $"Folder: {where}.\n" + (mine.Count == 0
            ? "No characters in it yet: put each one in a folder of its own inside it."
            : $"From it: {string.Join(", ", mine)}.") + (note == null ? "" : $"\n{note}");
    }

    void PickFolder(AUri? startAt)
    {
        if (startAt == null && CharacterFolder.Chosen(this, out _) is { } tree)
            startAt = Android.Provider.DocumentsContract.BuildDocumentUriUsingTree(tree,
                Android.Provider.DocumentsContract.GetTreeDocumentId(tree));
        try
        {
            StartActivityForResult(CharacterFolder.PickerIntent(startAt), PickFolderRequest);
        }
        catch (ActivityNotFoundException)
        {
            Toast.MakeText(this, "This phone has no folder picker for DeskDancer to use.", ToastLength.Long)!.Show();
        }
    }

    protected override void OnActivityResult(int requestCode, Result resultCode, Intent? data)
    {
        base.OnActivityResult(requestCode, resultCode, data);
        if (requestCode != PickFolderRequest) return;
        if (resultCode != Result.Ok || data?.Data is not { } tree)
        {
            Android.Util.Log.Info(MateOverlay.Tag, "folder picker closed without a folder");
            return;
        }
        try
        {
            CharacterFolder.Remember(this, tree, data.Flags);
        }
        catch (Exception ex)
        {
            Log.Error("Could not keep access to the characters folder", ex);
            Toast.MakeText(this, "DeskDancer could not keep access to that folder.", ToastLength.Long)!.Show();
            return;
        }
        Android.Util.Log.Info(MateOverlay.Tag, $"characters folder chosen: {tree}");
        FillFolder();
        SyncFolder(announce: true);
    }

    void OpenFolder()
    {
        if (CharacterFolder.Chosen(this, out _) is not { } tree) return;
        bool opened = CharacterFolder.Open(this, tree);
        Android.Util.Log.Info(MateOverlay.Tag, opened ? "characters folder opened" : "no app could open the characters folder");
        if (!opened)
            Toast.MakeText(this, $"Open your Files app and go to {CharacterFolder.Describe(this, tree)}.", ToastLength.Long)!.Show();
    }

    void ForgetFolder()
    {
        CharacterFolder.Forget(this);
        Android.Util.Log.Info(MateOverlay.Tag, "characters folder forgotten");
        Rescan();
        FillFolder();
    }

    /// <summary>Brings the copies up to date with the folder, on another thread, then shows what changed.</summary>
    void SyncFolder(bool announce)
    {
        var tree = CharacterFolder.Chosen(this, out bool lostAccess);
        if (tree == null || lostAccess)
        {
            FillFolder();
            return;
        }
        if (announce) _folderStatus.Text = "Reading your characters…";
        var context = ApplicationContext!;
        Task.Run(() => CharacterFolder.Sync(context, tree)).ContinueWith(done => RunOnUiThread(() =>
        {
            if (IsDestroyed || done.Result is not { } result) return;     // gone, or another sync is already at it
            Android.Util.Log.Info(MateOverlay.Tag,
                $"characters folder synced: {result.Characters.Count} character(s) ({string.Join(", ", result.Characters)}), " +
                $"{result.Copied} file(s) copied, {result.Removed} removed{(result.Problem == null ? "" : ", problem: " + result.Problem)}");
            if (result.Changed || announce) Rescan();
            FillFolder(result.Problem);
            if (announce)
            {
                string found = result.Characters.Count switch
                {
                    0 => "No characters found in the folder.",
                    1 => $"Found {result.Characters[0]}.",
                    int n => $"Found {n} characters.",
                };
                Toast.MakeText(this, found, ToastLength.Short)!.Show();
            }
        }));
    }

    /// <summary>Looks through the characters again, and has the mate on the screen read its own afresh.</summary>
    void Rescan()
    {
        Stage.Library.Scan();
        FillCharacters();
        FillMoves();
        if (MateService.Running) Send(MateService.ActionReload);
    }

    // ---- Moves to use ----

    /// <summary>
    /// The checklist of moves, as in the desktop's "Moves to use" menu: this character's own
    /// dances, then the built-in moves, each ticked while it is in use. The last built-in move
    /// still on cannot be unticked, so there is always something to dance.
    /// </summary>
    void FillMoves()
    {
        _filling = true;
        _movesList.RemoveAllViews();
        _moveBoxes.Clear();
        var character = Stage.Library.Load(Stage.CharacterId);
        var all = Moves.ForCharacter(character, Stage.Clock.Bpm);

        void Heading(string text)
        {
            var view = new TextView(this) { Text = text };
            view.SetTextSize(Android.Util.ComplexUnitType.Sp, 14);
            view.SetPadding(0, Dp(12), 0, Dp(4));
            _movesList.AddView(view);
        }
        void Box(DanceMove move)
        {
            string key = Moves.KeyOf(move, character.Id);
            bool builtIn = move.Clip == null;
            var box = new CheckBox(this) { Text = move.Name };
            box.CheckedChange += (_, e) =>
            {
                if (_filling) return;
                if (builtIn && !e.IsChecked && LastBuiltIn())
                {
                    RefreshMoves();
                    return;
                }
                Stage.Settings.SetMoveEnabled(key, e.IsChecked);
                Stage.Settings.Save();
                Android.Util.Log.Info(MateOverlay.Tag, $"move '{key}' switched {(e.IsChecked ? "on" : "off")}");
                RefreshMoves();
            };
            _moveBoxes[key] = (box, builtIn);
            _movesList.AddView(box);
        }

        var own = all.Where(m => m.Clip != null).ToList();
        if (own.Count > 0)
        {
            Heading($"{character.DisplayName}'s own dances");
            own.ForEach(Box);
        }
        Heading("Built-in moves");
        foreach (var move in all.Where(m => m.Clip == null)) Box(move);

        var allOn = new Button(this) { Text = "Switch them all back on" };
        allOn.Click += (_, _) =>
        {
            foreach (string key in _moveBoxes.Keys) Stage.Settings.SetMoveEnabled(key, true);
            Stage.Settings.Save();
            Android.Util.Log.Info(MateOverlay.Tag, "every move switched back on");
            RefreshMoves();
        };
        _movesList.AddView(allOn);
        _filling = false;
        RefreshMoves();
    }

    bool LastBuiltIn() => Moves.All.Count(m => Stage.Settings.MoveEnabled(m.Id)) <= 1;

    void RefreshMoves()
    {
        _filling = true;
        bool last = LastBuiltIn();
        foreach (var (key, (box, builtIn)) in _moveBoxes)
        {
            bool on = Stage.Settings.MoveEnabled(key);
            box.Checked = on;
            box.Enabled = !(builtIn && on && last);
        }
        int count = _moveBoxes.Keys.Count(Stage.Settings.MoveEnabled);
        bool open = _movesList.Visibility == ViewStates.Visible;
        _movesHeader.Text = $"Moves to use: {count} of {_moveBoxes.Count} on {(open ? "▾" : "▸")}";
        _filling = false;
    }

    /// <summary>Opens the list of moves and, given one, scrolls it into the middle of the screen.</summary>
    void ShowMoves(string? key)
    {
        _movesList.Visibility = ViewStates.Visible;
        RefreshMoves();
        View target = key != null && _moveBoxes.TryGetValue(key, out var entry) ? entry.Box : _movesHeader;
        _scroll.PostDelayed(() =>
        {
            int top = target.Top;
            for (var parent = target.Parent as View; parent != null && parent != _scroll.GetChildAt(0); parent = parent.Parent as View)
                top += parent.Top;
            _scroll.ScrollTo(0, Math.Max(0, top - _scroll.Height / 3));
            Android.Util.Log.Info(MateOverlay.Tag, $"moves shown{(key == null ? "" : $", scrolled to '{key}'")}");
        }, 400);
    }

    // ---- The mate ----

    void Start(string? character)
    {
        if (!CanDrawOverlays)
        {
            Toast.MakeText(this, "Allow display over other apps first.", ToastLength.Long)!.Show();
            Refresh();
            return;
        }
        Send(MateService.ActionShow, character);
        Refresh();
    }

    void Send(string action, string? character = null)
    {
        var intent = new Intent(this, typeof(MateService)).SetAction(action);
        if (character != null) intent.PutExtra(MateService.ExtraCharacter, character);
        StartForegroundService(intent);
    }

    void Stop()
    {
        StopService(new Intent(this, typeof(MateService)));
        Refresh();
    }

    void HandleCommand(Intent? intent)
    {
        string? command = intent?.GetStringExtra("command");
        if (intent == null || command == null) return;
        intent.RemoveExtra("command");
        string? character = intent.GetStringExtra("character");
        if (intent.GetBooleanExtra("calm", false))
        {
            Stage.Settings.Persist = false;
            Stage.Settings.Wander = false;
            Stage.Settings.AutoDance = false;
        }
        Android.Util.Log.Info(MateOverlay.Tag, $"command '{command}'{(character == null ? "" : $" character '{character}'")}");
        switch (command)
        {
            case "start": Start(character); break;
            case "dance": Send(MateService.ActionDance); break;
            case "rest": Send(MateService.ActionRest); break;
            case "stop": Stop(); break;
            case "reload": SyncFolder(announce: true); break;
            // These need the screen, or open something over it, so it stays.
            case "choose-folder":
                PickFolder(intent.GetStringExtra("folder") is { } path ? CharacterFolder.OnPhone(path) : null);
                return;
            case "open-folder": OpenFolder(); return;
            case "show-moves": ShowMoves(intent.GetStringExtra("move")); return;
        }
        MoveTaskToBack(true);
    }
}
