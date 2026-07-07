Option Explicit

Dim fso, shell, scriptDir, toolkitRoot, pythonw, modulePath, args, i, command, env
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
toolkitRoot = fso.GetParentFolderName(scriptDir)
pythonw = toolkitRoot & "\.venv\Scripts\pythonw.exe"

If Not fso.FileExists(pythonw) Then
    MsgBox "XRD_Toolkit environment was not found." & vbCrLf & vbCrLf & _
           "Run setup_env.bat from the XRD_Analysis_Toolkit folder first.", _
           vbExclamation, "XRD Phase Finder"
    WScript.Quit 1
End If

Set env = shell.Environment("PROCESS")
modulePath = toolkitRoot & "\XRD_Finder"
If Len(env("PYTHONPATH")) > 0 Then
    env("PYTHONPATH") = modulePath & ";" & env("PYTHONPATH")
Else
    env("PYTHONPATH") = modulePath
End If

args = ""
For i = 0 To WScript.Arguments.Count - 1
    args = args & " " & Quote(WScript.Arguments(i))
Next

shell.CurrentDirectory = toolkitRoot
command = Quote(pythonw) & " -m xrd_finder.apps.finder_gui" & args
shell.Run command, 0, False

Function Quote(value)
    Quote = Chr(34) & Replace(CStr(value), Chr(34), Chr(34) & Chr(34)) & Chr(34)
End Function
