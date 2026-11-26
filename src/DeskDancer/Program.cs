using Avalonia;
using Avalonia.Controls;
using DeskDancer.Tools;
using DeskDancer.Updates;
using Velopack;

namespace DeskDancer;

/// <summary>Command-line switches. Running with none just starts the mate.</summary>
public sealed class CliOptions
{
    public bool Help, Version, Fresh, SmokeTest, Screenshots, Verbose;
    public string? Character, CharactersFolder, ExportSample, RenderTest, Out, UpdateFeed;
    public double Seconds = 12;
    public string? Error;

    public bool IsTool => ExportSample != null || RenderTest != null;

    public const string HelpText = """
        DeskDancer - a dancing desktop mate

        Usage: DeskDancer [options]

          --character <id>        Start with this character ("builtin" or a folder name)
          --characters <folder>   Also look for character folders here
          --fresh                 Ignore saved settings for this run
          --verbose               Print state changes to the console
          --help, --version

        Developer tools:
          --export-sample <dir>   Write the built-in character out as an example image pack
          --render-test <dir>     Render every dance move to PNG contact sheets
          --update-feed <where>   Look for new versions in this folder or at this web address
                                  instead of on GitHub, and look straight away: for trying
                                  updates out
          --smoke-test            Start, exercise every feature for a few seconds, exit 0 on success
          --seconds <n>           How long the smoke test runs (default 12)
          --out <dir>             Where the smoke test saves its snapshots
          --screenshots           macOS: let the smoke test take screenshots, to check what is
                                  really on the screen. Screen recording has to be allowed.
        """;

    public static CliOptions Parse(string[] args)
    {
        var o = new CliOptions();
        for (int i = 0; i < args.Length; i++)
        {
            string a = args[i];
            string? Next() => i + 1 < args.Length ? args[++i] : null;
            switch (a)
            {
                case "--help" or "-h" or "/?": o.Help = true; break;
                case "--version": o.Version = true; break;
                case "--fresh": o.Fresh = true; break;
                case "--verbose": o.Verbose = true; break;
                case "--smoke-test": o.SmokeTest = true; break;
                case "--screenshots": o.Screenshots = true; break;
                case "--character": o.Character = Next(); break;
                case "--characters": o.CharactersFolder = Next(); break;
                case "--export-sample": o.ExportSample = Next(); break;
                case "--render-test": o.RenderTest = Next(); break;
                case "--out": o.Out = Next(); break;
                case "--update-feed": o.UpdateFeed = Next(); break;
                case "--seconds":
                    if (!double.TryParse(Next(), System.Globalization.CultureInfo.InvariantCulture, out o.Seconds))
                        o.Error = "--seconds needs a number";
                    break;
                default: o.Error = $"Unknown option: {a}"; break;
            }
        }
        return o;
    }
}

internal static class Program
{
    [STAThread]
    public static int Main(string[] args)
    {
        // Velopack comes first. While a version is being installed, updated or removed it
        // runs this program with arguments of its own, and this answers them and exits. A
        // newer version that was downloaded the last time is put in here too, and the
        // program started again: but not when it was only asked a question or to run a
        // test, which should be answered by the copy that was asked. Nothing else of
        // DeskDancer's own may run before this.
        bool passingThrough = args.Any(a => a is "--version" or "--help" or "-h" or "/?" or "--smoke-test" or "--render-test" or "--export-sample");
        VelopackApp.Build().SetAutoApplyOnStartup(!passingThrough).Run();

        var options = CliOptions.Parse(args);
        if (options.Error != null)
        {
            Console.Error.WriteLine(options.Error);
            Console.Error.WriteLine(CliOptions.HelpText);
            return 2;
        }
        if (options.Help)
        {
            Console.WriteLine(CliOptions.HelpText);
            return 0;
        }
        if (options.Version)
        {
            Console.WriteLine(Updater.CurrentVersion());
            return 0;
        }

        Log.Verbose = options.Verbose;
        App.Options = options;
        AppDomain.CurrentDomain.UnhandledException += (_, e) =>
            Log.Error("Unhandled exception", e.ExceptionObject as Exception);

        try
        {
            if (options.IsTool)
            {
                // The render tools need the drawing stack but no windows.
                BuildAvaloniaApp().SetupWithoutStarting();
                return DevTools.Run(options);
            }
            return BuildAvaloniaApp().StartWithClassicDesktopLifetime(args, ShutdownMode.OnExplicitShutdown);
        }
        catch (Exception ex)
        {
            Log.Error("DeskDancer stopped unexpectedly", ex);
            return 1;
        }
    }

    public static AppBuilder BuildAvaloniaApp() =>
        AppBuilder.Configure<App>()
            .UsePlatformDetect()
            .WithInterFont()
            .LogToTrace();
}
