using Android.App;
using Android.Content;
using Android.Content.PM;
using Android.Graphics.Drawables;
using Android.OS;

namespace DeskDancer.Droid;

/// <summary>
/// Keeps the mate on the screen while other apps are in front. Android only lets that go on
/// for a service that shows a notification, which doubles as its remote: tap it for the
/// settings, or use its Dance and Put away buttons.
/// </summary>
[Service(Name = "io.github.friendlyuser.deskdancer.MateService", Exported = false,
         ForegroundServiceType = ForegroundService.TypeSpecialUse)]
public sealed class MateService : Service
{
    public const string ActionShow = "io.github.friendlyuser.deskdancer.SHOW";
    public const string ActionDance = "io.github.friendlyuser.deskdancer.DANCE";
    public const string ActionStop = "io.github.friendlyuser.deskdancer.STOP";
    public const string ActionRest = "io.github.friendlyuser.deskdancer.REST";
    /// <summary>Reads the mate's character afresh, after the characters were scanned again.</summary>
    public const string ActionReload = "io.github.friendlyuser.deskdancer.RELOAD";
    public const string ExtraCharacter = "character";

    const int NotificationId = 1;
    const string ChannelId = "mate";

    MateOverlay? _overlay;

    public static bool Running { get; private set; }

    public override IBinder? OnBind(Intent? intent) => null;

    public override StartCommandResult OnStartCommand(Intent? intent, StartCommandFlags flags, int startId)
    {
        string action = intent?.Action ?? ActionShow;
        if (action == ActionStop)
        {
            StopForeground(StopForegroundFlags.Remove);
            StopSelf();
            return StartCommandResult.NotSticky;
        }

        // Started with startForegroundService, this has to happen within a few seconds.
        GoForeground();
        Running = true;
        try
        {
            Stage.EnsureReady(this);
            string? character = intent?.GetStringExtra(ExtraCharacter);
            if (character != null) Stage.CharacterId = character;
            if (_overlay == null)
                _overlay = new MateOverlay(this, Stage.CharacterId);
            else if (action == ActionReload)
                _overlay.SetCharacter(Stage.CharacterId);
            else if (character != null && !character.Equals(_overlay.Character.Id, StringComparison.OrdinalIgnoreCase))
                _overlay.SetCharacter(character);
            _overlay.Refresh();
            if (action == ActionDance) _overlay.ToggleDance();
            else if (action == ActionRest) _overlay.Rest();
        }
        catch (Exception ex)
        {
            Log.Error("Could not put the mate on the screen", ex);
            Android.Util.Log.Error(MateOverlay.Tag, ex.ToString());
            StopSelf();
            return StartCommandResult.NotSticky;
        }
        return StartCommandResult.Sticky;
    }

    public override void OnDestroy()
    {
        _overlay?.Close();
        _overlay = null;
        Running = false;
        base.OnDestroy();
    }

    void GoForeground()
    {
        var manager = (NotificationManager)GetSystemService(NotificationService)!;
        if (manager.GetNotificationChannel(ChannelId) == null)
        {
            manager.CreateNotificationChannel(new NotificationChannel(ChannelId, "Mate on screen", NotificationImportance.Low)
            {
                Description = "Shown while a mate is on the screen. Android needs it to keep the mate there.",
            });
        }

        var openSettings = PendingIntent.GetActivity(this, 0, new Intent(this, typeof(MainActivity)),
            PendingIntentFlags.Immutable | PendingIntentFlags.UpdateCurrent);
        var dance = PendingIntent.GetService(this, 1, new Intent(this, typeof(MateService)).SetAction(ActionDance),
            PendingIntentFlags.Immutable | PendingIntentFlags.UpdateCurrent);
        var stop = PendingIntent.GetService(this, 2, new Intent(this, typeof(MateService)).SetAction(ActionStop),
            PendingIntentFlags.Immutable | PendingIntentFlags.UpdateCurrent);
        var icon = Icon.CreateWithResource(this, Android.Resource.Drawable.IcMediaPlay);

        var notification = new Notification.Builder(this, ChannelId)
            .SetSmallIcon(Android.Resource.Drawable.IcMediaPlay)
            .SetContentTitle("DeskDancer")
            .SetContentText("Your mate is on the screen. Tap for settings.")
            .SetContentIntent(openSettings)
            .SetOngoing(true)
            .AddAction(new Notification.Action.Builder(icon, "Dance", dance).Build())
            .AddAction(new Notification.Action.Builder(icon, "Put away", stop).Build())
            .Build();

        if (OperatingSystem.IsAndroidVersionAtLeast(34))
            StartForeground(NotificationId, notification, ForegroundService.TypeSpecialUse);
        else
            StartForeground(NotificationId, notification);
    }
}
