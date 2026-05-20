' launch.vbs — silent launcher for FinanceOS.
'
' Double-click this file to start FinanceOS without any terminal window.
' The Streamlit process starts hidden in the background; your default
' browser opens to http://127.0.0.1:8501 as usual.
'
' To STOP the app later, double-click stop.bat (it kills whatever is
' listening on port 8501).
'
' If something breaks at startup and you don't know why, run run.bat
' instead — that keeps the terminal visible so you can read the error.

Dim shell, fso, projectRoot
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

projectRoot = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = projectRoot

' Make sure the venv exists — otherwise show a friendly error and bail.
If Not fso.FileExists(projectRoot & "\.venv\Scripts\activate.bat") Then
    MsgBox _
        "Virtual environment not found." & vbCrLf & vbCrLf & _
        "Open PowerShell in this folder and run first-time setup:" & vbCrLf & _
        "    py -m venv .venv" & vbCrLf & _
        "    .\.venv\Scripts\Activate.ps1" & vbCrLf & _
        "    pip install -r requirements.txt" & vbCrLf & vbCrLf & _
        "Then try launch.vbs again.", _
        vbCritical, "FinanceOS"
    WScript.Quit
End If

' Window style 0 = hidden. False = don't wait for return (fire and forget).
shell.Run "cmd /c """ & projectRoot & "\run.bat""", 0, False
