/*
 * minidspqt.exe — GUI launcher for the bundled CPython.
 *
 * Loads python3xx.dll from its own directory and hands control to Py_Main with
 * the argument vector `minidspqt.exe -m minidspqt.cli <user args>`. That is the
 * whole job: the ._pth file next to the DLL already puts the interpreter in
 * isolated mode with the bundled site-packages on sys.path, so no environment
 * variables and no path fiddling are needed here.
 *
 * Why a launcher at all instead of a shortcut to pythonw.exe:
 *   - the process shows up as minidspqt.exe in Task Manager and the taskbar,
 *   - the exe carries the icon and version info (see launcher.rc.in), so the
 *     portable zip is double-clickable,
 *   - it is a GUI-subsystem binary, so no console window flashes.
 *
 * Cross-compiled on Linux with mingw-w64 by packaging/windows/build.py:
 *   x86_64-w64-mingw32-gcc -municode -mwindows -DPYTHON_DLL=L"python313.dll" ...
 *
 * Deliberately no AppUserModelID: Windows derives one from the exe path, which
 * is exactly right for a single plain executable and keeps taskbar pinning
 * working. Setting an explicit ID only in the exe would break it.
 */

#include <windows.h>
#include <shellapi.h>
#include <stdlib.h>
#include <wchar.h>

#ifndef PYTHON_DLL
#error "PYTHON_DLL must be defined, e.g. -DPYTHON_DLL=L\"python313.dll\""
#endif

typedef int (*Py_Main_t)(int argc, wchar_t **argv);

static void die(const wchar_t *what)
{
    wchar_t msg[512];
    DWORD err = GetLastError();
    _snwprintf(msg, 512,
               L"%ls\n\nThe application folder seems incomplete. "
               L"Re-extract the zip or re-run the installer.\n(Windows error %lu)",
               what, (unsigned long)err);
    MessageBoxW(NULL, msg, L"minidspqt", MB_ICONERROR | MB_OK);
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR cmdline, int show)
{
    (void)inst; (void)prev; (void)cmdline; (void)show;

    /* Directory of this executable: python3xx.dll and the ._pth live there. */
    wchar_t exe_dir[MAX_PATH];
    DWORD n = GetModuleFileNameW(NULL, exe_dir, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) {
        die(L"Could not determine the application folder.");
        return 1;
    }
    wchar_t *slash = wcsrchr(exe_dir, L'\\');
    if (slash) *slash = L'\0';

    wchar_t dll_path[MAX_PATH];
    _snwprintf(dll_path, MAX_PATH, L"%ls\\%ls", exe_dir, PYTHON_DLL);

    /* Dependencies of the DLL (vcruntime140.dll, python3.dll) sit beside it;
       LOAD_WITH_ALTERED_SEARCH_PATH makes the loader look there first. */
    HMODULE py = LoadLibraryExW(dll_path, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!py) {
        die(L"Could not load " PYTHON_DLL L".");
        return 1;
    }
    Py_Main_t py_main = (Py_Main_t)(void (*)(void))GetProcAddress(py, "Py_Main");
    if (!py_main) {
        die(L"Py_Main not found in " PYTHON_DLL L".");
        return 1;
    }

    int argc = 0;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (!argv || argc < 1) {
        die(L"Could not parse the command line.");
        return 1;
    }

    /* argv[0] stays the exe path (Python reports it as sys.executable). */
    wchar_t **py_argv = (wchar_t **)calloc((size_t)argc + 3, sizeof(wchar_t *));
    if (!py_argv) return 1;
    py_argv[0] = argv[0];
    py_argv[1] = L"-m";
    py_argv[2] = L"minidspqt.cli";
    for (int i = 1; i < argc; i++) py_argv[i + 2] = argv[i];

    int rc = py_main(argc + 2, py_argv);
    free(py_argv);
    LocalFree(argv);
    return rc;
}
