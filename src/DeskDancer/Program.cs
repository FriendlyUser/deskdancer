using Avalonia;
using Avalonia.Controls;
using DeskDancer.Tools;

namespace DeskDancer;

/// <summary>Command-line switches. Running with none just starts the mate.</summary>
public sealed class CliOptions
{
    public bool Help, Version, Fresh, SmokeTest, Verbose;
    public string? Character, CharactersFolder, ExportSample, RenderTest, Out;
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
          --smoke-test            Start, exercise every feature for a few seconds, exit 0 on success
          --seconds <n>           How long the smoke test runs (default 12)
          --out <dir>             Where the smoke test saves its snapshots
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
                case "--character": o.Character = Next(); break;
                case "--characters": o.CharactersFolder = Next(); break;
                case "--export-sample": o.ExportSample = Next(); break;
                case "--render-test": o.RenderTest = Next(); break;
                case "--out": o.Out = Next(); break;
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
            Console.WriteLine(typeof(Program).Assembly.GetName().Version?.ToString(3) ?? "unknown");
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
