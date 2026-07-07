Option Explicit
Dim fso, shell, scriptDir, appRoot, previewScript, command
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
appRoot = fso.GetParentFolderName(scriptDir)
previewScript = appRoot & "\toolkit\launch_xrd_finder_preview.ps1"

If Not fso.FileExists(previewScript) Then
    MsgBox "Startup preview script was not found." & vbCrLf & previewScript, vbExclamation, "XRD Phase Finder"
    WScript.Quit 1
End If

command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File " & Quote(previewScript) & " -AppId xrd_finder"
shell.Run command, 0, False

Function Quote(value)
    Quote = Chr(34) & Replace(CStr(value), Chr(34), Chr(34) & Chr(34)) & Chr(34)
End Function
