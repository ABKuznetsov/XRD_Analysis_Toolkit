Option Explicit
Dim fso, shell, scriptDir, appRoot, previewScript, command, argument
Dim sciRoot, pythonw, fastStart, fastCode
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
appRoot = scriptDir
previewScript = appRoot & "\launcher\launch_xrd_finder_preview.ps1"

' A healthy Sci installation can open Finder without starting PowerShell.
' Exit 75 retains the existing installation/repair interface below.
sciRoot = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Sci"
pythonw = sciRoot & "\env\Scripts\pythonw.exe"
fastStart = appRoot & "\launcher\fast_start.py"
If fso.FileExists(pythonw) And fso.FileExists(fastStart) Then
    command = Quote(pythonw) & " " & Quote(fastStart) _
        & " --data-root " & Quote(sciRoot & "\apps\xrd_phase_finder\data") _
        & " --logs-root " & Quote(sciRoot & "\logs")
    If WScript.Arguments.Count > 0 Then
        command = command & " --project " & Quote(WScript.Arguments.Item(0))
    End If
    On Error Resume Next
    fastCode = shell.Run(command, 0, True)
    If Err.Number <> 0 Then
        fastCode = 75
        Err.Clear
    End If
    On Error GoTo 0
    If fastCode = 0 Then WScript.Quit 0
    If fastCode <> 75 Then
        MsgBox "Finder could not open. See the startup log:" & vbCrLf _
            & sciRoot & "\logs\xrd_finder_console.log", vbExclamation, "XRD Phase Finder"
        WScript.Quit fastCode
    End If
End If

If Not fso.FileExists(previewScript) Then
    MsgBox "Startup preview script was not found." & vbCrLf & previewScript, vbExclamation, "XRD Phase Finder"
    WScript.Quit 1
End If

command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File " & Quote(previewScript) & " -AppId xrd_finder"
If WScript.Arguments.Count > 0 Then
    argument = WScript.Arguments.Item(0)
    command = command & " -ProjectPath " & Quote(argument)
End If
shell.Run command, 0, False

Function Quote(value)
    Quote = Chr(34) & Replace(CStr(value), Chr(34), Chr(34) & Chr(34)) & Chr(34)
End Function
