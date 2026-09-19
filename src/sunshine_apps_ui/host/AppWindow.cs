// SPDX-License-Identifier: GPL-3.0-or-later
//
// The window the app manager is shown in on Windows.
//
// **Why there is C# in a Python program.** Everything here was a browser
// until it was measured. Driving a browser as a window costs a table of
// per-browser flags, a seeded Firefox profile, a profile directory, a job
// object to close it, and a rule for every browser about what "fullscreen"
// means -- and it put the app on screen in 3.6 seconds. A WebView2 window
// does it in 1.5, with the window itself up in 0.36, and needs none of that
// machinery. Measured on the rig, 2026-09-18, in the interactive session.
//
// **Why it is not compiled by us and shipped as a binary.** It is compiled on
// the machine it runs on, by the csc.exe that is part of Windows
// (%WINDIR%\Microsoft.NET\Framework64\v4.0.30319). Nothing is downloaded to
// build it and no toolchain is installed. That keeps the property the bundled
// interpreter was built around: what runs here is readable where it runs.
// This file is the whole of it.
//
// It is deliberately C# 5 -- no string interpolation, no null-conditional
// operators -- because that is what the in-box compiler accepts.
//
// Arguments, all optional but the URL:
//   <url>                     what to show
//   --user-data-dir=<path>    where WebView2 keeps its profile; also how the
//                             launcher recognises this window as one of ours
//   --fullscreen              no border, fills the screen (streamed)
//   --windowed                keeps its frame, maximised (at the machine)
//   --check                   start nothing; exit 0 if a WebView2 runtime is
//                             usable, 3 if not. How the installer knows the
//                             build works before trusting it.
//
// Exit codes: 0 normal, 2 bad arguments, 3 no usable WebView2 runtime.

using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

class AppWindow {
    // The starting page's own background. The window appears long before the
    // page is in it, and a white rectangle on a television is a flash of
    // light in a dark room.
    static readonly Color Background = Color.FromArgb(0x21, 0x25, 0x29);

    const int ExitBadArguments = 2;
    const int ExitNoRuntime = 3;

    static Form form;
    static WebView2 view;
    static string userDataFolder;

    [STAThread]
    static int Main(string[] args) {
        string url = "";
        bool fullscreen = false;

        foreach (string arg in args) {
            if (arg == "--check") return Check();
            else if (arg == "--fullscreen") fullscreen = true;
            else if (arg == "--windowed") fullscreen = false;
            else if (arg.StartsWith("--user-data-dir=")) userDataFolder = arg.Substring(16);
            else if (arg.StartsWith("--")) { /* ignored, not fatal */ }
            else if (url == "") url = arg;
        }

        if (url == "") {
            Console.Error.WriteLine("AppWindow: no URL given.");
            return ExitBadArguments;
        }
        if (string.IsNullOrEmpty(userDataFolder))
            userDataFolder = Path.Combine(Path.GetTempPath(), "sunshine-apps-ui-window");

        // Asked before a window exists, so that a machine without the runtime
        // gets the browser instead of a window that appears and vanishes.
        if (AvailableRuntime() == "") {
            Console.Error.WriteLine("AppWindow: no WebView2 runtime on this machine.");
            return ExitNoRuntime;
        }

        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);

        form = new Form();
        form.Text = "App Manager";
        form.BackColor = Background;
        form.WindowState = FormWindowState.Maximized;
        // Sean's rule, 2026-09-17: streamed through Moonlight nothing should
        // frame the page; opened at the machine, a window you cannot move or
        // close is hostile.
        if (fullscreen) form.FormBorderStyle = FormBorderStyle.None;

        view = new WebView2();
        view.Dock = DockStyle.Fill;
        view.DefaultBackgroundColor = Background;
        view.CreationProperties = new CoreWebView2CreationProperties();
        view.CreationProperties.UserDataFolder = userDataFolder;

        view.CoreWebView2InitializationCompleted +=
            new EventHandler<CoreWebView2InitializationCompletedEventArgs>(Initialized);

        form.Controls.Add(view);
        // Navigation starts once the form has a real window handle. Setting
        // Source before Application.Run gets the control's handle recreated
        // underneath it, and WebView2 fails with ERROR_INVALID_WINDOW_HANDLE
        // (0x80070578) -- which is exactly what the first build did.
        form.Shown += delegate { view.Source = new Uri(url); };

        Application.Run(form);
        return 0;
    }

    /// <summary>Is there a runtime, and can the loader find it?</summary>
    /// Also proves the two managed assemblies and the native loader beside
    /// this executable all load, which is what --check is really asking.
    static string AvailableRuntime() {
        try {
            return CoreWebView2Environment.GetAvailableBrowserVersionString();
        } catch (Exception) {
            return "";
        }
    }

    static int Check() {
        string version = AvailableRuntime();
        if (version == "") return ExitNoRuntime;
        return 0;
    }

    static void Initialized(object sender, CoreWebView2InitializationCompletedEventArgs e) {
        if (!e.IsSuccess) {
            // The precheck said there was a runtime, so this is something else
            // -- a profile directory that cannot be written, most likely.
            string why = e.InitializationException == null
                ? "unknown" : e.InitializationException.Message;
            Console.Error.WriteLine("AppWindow: WebView2 would not start: " + why);
            Environment.Exit(ExitNoRuntime);
        }

        CoreWebView2 core = view.CoreWebView2;
        // The window is the app, not a browser: it has no address bar, so a
        // link that leaves the app would strand whoever followed it with no
        // way back. Anything not ours goes to the real browser instead.
        core.NewWindowRequested +=
            new EventHandler<CoreWebView2NewWindowRequestedEventArgs>(NewWindow);
        core.NavigationStarting +=
            new EventHandler<CoreWebView2NavigationStartingEventArgs>(Navigating);
        core.DocumentTitleChanged += delegate {
            form.Text = core.DocumentTitle;
        };
        // Nothing here wants a download manager or a default context menu on a
        // television, but both are how someone at the machine saves a log.
        // Left alone deliberately.
    }

    static bool IsOurs(string url) {
        if (string.IsNullOrEmpty(url)) return true;
        Uri parsed;
        if (!Uri.TryCreate(url, UriKind.Absolute, out parsed)) return true;
        if (parsed.IsFile) return true;                     // the starting page
        if (parsed.Scheme != "http" && parsed.Scheme != "https") return false;
        return parsed.IsLoopback;                           // our own server
    }

    static void OpenOutside(string url) {
        try {
            Process.Start(url);
        } catch (Exception e) {
            Console.Error.WriteLine("AppWindow: could not hand " + url +
                                    " to the browser: " + e.Message);
        }
    }

    static void NewWindow(object sender, CoreWebView2NewWindowRequestedEventArgs e) {
        e.Handled = true;
        OpenOutside(e.Uri);
    }

    static void Navigating(object sender, CoreWebView2NavigationStartingEventArgs e) {
        if (IsOurs(e.Uri)) return;
        e.Cancel = true;
        OpenOutside(e.Uri);
    }
}
