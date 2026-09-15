; NSIS installer for minidspqt — built on Linux by packaging/windows/build.py:
;
;   makensis -DVERSION=X.Y.Z -DSRCDIR=build/windows/app -DOUTFILE=dist/... \
;            -DICON=packaging/windows/minidspqt.ico -DLICENSE=LICENSE \
;            packaging/windows/minidspqt.nsi
;
; Design:
;   - Per-user install into %LOCALAPPDATA%\Programs\minidspqt. No admin rights,
;     no UAC prompt, no HKLM writes. Windows binds its inbox HID driver to the
;     DSP on its own, so there is nothing system-wide to set up.
;   - One Start Menu shortcut, an uninstaller, and the usual Add/Remove entry.
;   - Re-installing over an existing copy runs that copy's uninstaller first so
;     files pruned or renamed between versions cannot linger.
;   - The uninstaller removes what the installer wrote and nothing else. The
;     QSettings key HKCU\Software\miniDSP\minidspqt (theme choice) is left in
;     place; see the user guide.

Unicode true
SetCompressor /SOLID lzma

!ifndef VERSION
  !error "pass -DVERSION=X.Y.Z"
!endif
!ifndef SRCDIR
  !error "pass -DSRCDIR=<staged application tree>"
!endif
!ifndef OUTFILE
  !error "pass -DOUTFILE=<installer path>"
!endif
!ifndef ICON
  !error "pass -DICON=<.ico path>"
!endif
!ifndef LICENSE
  !error "pass -DLICENSE=<licence text file>"
!endif

!define APP_NAME    "minidspqt"
!define APP_EXE     "minidspqt.exe"
!define PUBLISHER   "miniDSP-Linux-qt project"
!define URL         "https://github.com/IMBArator/miniDSP-Linux-qt"
!define UNINST_KEY  "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"

Name "${APP_NAME} ${VERSION}"
OutFile "${OUTFILE}"
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\Programs\${APP_NAME}"
InstallDirRegKey HKCU "${UNINST_KEY}" "InstallLocation"
ShowInstDetails show
ShowUninstDetails show

; --- Modern UI -----------------------------------------------------------------

!include "MUI2.nsh"
!include "FileFunc.nsh"

!define MUI_ICON   "${ICON}"
!define MUI_UNICON "${ICON}"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APP_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Start ${APP_NAME}"

!insertmacro MUI_PAGE_LICENSE "${LICENSE}"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; --- Install -------------------------------------------------------------------

Section "Install"
  SetShellVarContext current

  ; Clean upgrade: run the previous uninstaller silently, in place.
  IfFileExists "$INSTDIR\Uninstall.exe" 0 +3
    DetailPrint "Removing the previous installation"
    ExecWait '"$INSTDIR\Uninstall.exe" /S _?=$INSTDIR'

  SetOutPath "$INSTDIR"
  File /r "${SRCDIR}/*"

  WriteUninstaller "$INSTDIR\Uninstall.exe"

  CreateShortCut "$SMPROGRAMS\${APP_NAME}.lnk" "$INSTDIR\${APP_EXE}" "" \
                 "$INSTDIR\${APP_EXE}" 0 "" "" "Graphical interface for the t.racks DSP 4x4 Mini"

  ; Add/Remove Programs entry (per-user).
  WriteRegStr   HKCU "${UNINST_KEY}" "DisplayName"          "${APP_NAME}"
  WriteRegStr   HKCU "${UNINST_KEY}" "DisplayVersion"       "${VERSION}"
  WriteRegStr   HKCU "${UNINST_KEY}" "Publisher"            "${PUBLISHER}"
  WriteRegStr   HKCU "${UNINST_KEY}" "URLInfoAbout"         "${URL}"
  WriteRegStr   HKCU "${UNINST_KEY}" "DisplayIcon"          "$INSTDIR\${APP_EXE}"
  WriteRegStr   HKCU "${UNINST_KEY}" "InstallLocation"      "$INSTDIR"
  WriteRegStr   HKCU "${UNINST_KEY}" "UninstallString"      '"$INSTDIR\Uninstall.exe"'
  WriteRegStr   HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1

  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" "$0"
SectionEnd

; --- Uninstall -----------------------------------------------------------------

Section "Uninstall"
  SetShellVarContext current

  Delete "$SMPROGRAMS\${APP_NAME}.lnk"

  ; Only what the installer wrote: the bundled site-packages tree, the
  ; interpreter files, and our own launcher/asset files. No recursive delete
  ; of $INSTDIR itself, so a user-chosen directory with other content is safe.
  RMDir /r "$INSTDIR\Lib"
  Delete "$INSTDIR\*.dll"
  Delete "$INSTDIR\*.pyd"
  Delete "$INSTDIR\*.exe"
  Delete "$INSTDIR\*.zip"
  Delete "$INSTDIR\*._pth"
  Delete "$INSTDIR\*.cat"
  Delete "$INSTDIR\*.txt"
  Delete "$INSTDIR\*.cmd"
  Delete "$INSTDIR\*.ico"
  RMDir "$INSTDIR"

  DeleteRegKey HKCU "${UNINST_KEY}"
SectionEnd
