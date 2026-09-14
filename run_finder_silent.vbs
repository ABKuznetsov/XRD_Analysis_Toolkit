Option Explicit
Dim fso, shell, scriptDir, launchScript, command
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
launchScript = scriptDir & "\launch_xrd_finder_silent.vbs"

If Not fso.FileExists(launchScript) Then
    MsgBox "XRD Phase Finder launcher was not found." & vbCrLf & launchScript, vbExclamation, "XRD Phase Finder"
    WScript.Quit 1
End If

command = "wscript.exe " & Quote(launchScript)
shell.Run command, 0, False

Function Quote(value)
    Quote = Chr(34) & Replace(CStr(value), Chr(34), Chr(34) & Chr(34)) & Chr(34)
End Function