using Android.App;
using Android.Runtime;
using Avalonia.Android;

namespace DeskDancer.Droid;

/// <summary>Starts Avalonia when the app's process starts, before any activity or service.</summary>
[Application]
public sealed class MainApplication : AvaloniaAndroidApplication<MobileApp>
{
    public MainApplication(IntPtr javaReference, JniHandleOwnership transfer)
        : base(javaReference, transfer)
    {
    }
}
