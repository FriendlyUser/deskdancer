using Android;
using Android.App;
using Android.Content;
using Android.Content.PM;
using Android.OS;
using Android.Views;
using Android.Widget;

namespace DeskDancer.Droid;

/// <summary>
/// The settings screen: permission, character, and buttons to put the mate on the screen,
/// make it dance and put it away. Long-pressing the mate brings this back.
///
/// Scripts can drive it too, which is how the CI test does:
/// <c>adb shell am start -n io.github.friendlyuser.deskdancer/.MainActivity --es command start|dance|rest|stop [--es character mochi]</c>
/// (<c>dance</c> starts or stops a dance; <c>rest</c> only stops one.)
/// After a command the screen gets out of the way, so the mate is seen over whatever was there.
/// Adding <c>--ez calm true</c> keeps the mate from wandering off or dancing unasked, and
/// leaves the saved settings alone, so screenshots catch it where it was put.
/// </summary>
[Activity(Name = "io.github.friendlyuser.deskdancer.MainActivity", Label = "DeskDancer",
          MainLauncher = true, Exported = true, LaunchMode = LaunchMode.SingleTask)]
public sealed class MainActivity : Activity
{
    TextView _status = null!;
    Button _allow = null!;
    RadioGroup _characters = null!;
    readonly Dictionary<int, string> _characterIds = [];

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
    }

    bool CanDrawOverlays => Android.Provider.Settings.CanDrawOverlays(this);

    View BuildUi()
    {
        int Dp(double v) => (int)Math.Round(v * Resources!.DisplayMetrics!.Density);
        var column = new LinearLayout(this) { Orientation = Orientation.Vertical };
        column.SetPadding(Dp(24), Dp(32), Dp(24), Dp(24));

        TextView Text(string text, float size)
        {
            var view = new TextView(this) { Text = text };
            view.SetTextSize(Android.Util.ComplexUnitType.Sp, size);
            view.SetPadding(0, Dp(8), 0, Dp(8));
            column.AddView(view);
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
        foreach (var info in Stage.Library.Available)
        {
            var radio = new RadioButton(this) { Text = info.Name, Id = View.GenerateViewId() };
            _characterIds[radio.Id] = info.Id;
            _characters.AddView(radio);
            if (info.Id.Equals(Stage.CharacterId, StringComparison.OrdinalIgnoreCase)) radio.Checked = true;
        }
        _characters.CheckedChange += (_, e) =>
        {
            if (!_characterIds.TryGetValue(e.CheckedId, out string? id)) return;
            Stage.CharacterId = id;
            if (MateService.Running) Send(MateService.ActionShow, id);
        };
        column.AddView(_characters);

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

        return new ScrollView(this) { FillViewport = true }.Also(s => s.AddView(column));
    }

    void Refresh()
    {
        bool allowed = CanDrawOverlays;
        _allow.Visibility = allowed ? ViewStates.Gone : ViewStates.Visible;
        _status.Text = !allowed
            ? "First, let DeskDancer display over other apps. Android asks you to switch this on yourself."
            : MateService.Running ? "Your mate is on the screen." : "Ready. Put the mate on the screen below.";
    }

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
        }
        MoveTaskToBack(true);
    }
}

static class ViewExtensions
{
    public static T Also<T>(this T value, Action<T> action)
    {
        action(value);
        return value;
    }
}
