extern alias JB;
global using Nitrox.Model.Logger;
using System;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;
using JB::JetBrains.Annotations;
using Nitrox.Model.Core;
using Nitrox.Model.Subnautica.Logger;
using NitroxPatcher.Helper;
using UnityEngine;

namespace NitroxPatcher;

public static class Main
{
    /// <summary>
    ///     Lazily (i.e. when called, unlike immediately on class load) gets the path to the Nitrox Launcher folder.
    ///     This path can be anywhere on the system because it's placed somewhere the user likes. Doesn't test if the path exists.
    /// </summary>
    private static readonly Lazy<string> nitroxLauncherDir = new(() =>
    {
        // Get path from environment variable.
        string envPath = Environment.GetEnvironmentVariable(NitroxUser.LAUNCHER_PATH_ENV_KEY, EnvironmentVariableTarget.Process);
        if (!string.IsNullOrEmpty(envPath))
        {
            return envPath;
        }

        // Get path from command args.
        string[] args = Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length - 1; i++)
        {
            string path = (args[i], args[i + 1]) switch
            {
                ("--nitrox", { } value) when Directory.Exists(value) => Path.GetFullPath(value),
                _ => null
            };
            if (!string.IsNullOrEmpty(path))
            {
                Environment.SetEnvironmentVariable(NitroxUser.LAUNCHER_PATH_ENV_KEY, path, EnvironmentVariableTarget.Process);
                return path;
            }
        }

        return string.Empty;
    });

    private static readonly char[] newLineChars = Environment.NewLine.ToCharArray();
    private static bool initialized;

    /// <summary>
    ///     Entrypoint of Nitrox. Code in this method cannot use other dependencies (DLLs) without crashing
