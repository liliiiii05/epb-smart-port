@echo off
title Création du raccourci - EPB
color 0A
echo ========================================
echo    CRÉATION DU RACCOURCI EPB
echo ========================================
echo.

cd /d "C:\Users\AB\mon_projet_epb\epb_smart"

echo 📁 Dossier : %cd%
echo.

:: Créer directement le raccourci avec VBS
echo Création du raccourci avec icône de bateau...

(
echo Set shell = CreateObject("WScript.Shell")
echo Set shortcut = shell.CreateShortcut("%USERPROFILE%\Desktop\EPB Port de Béjaïa.lnk")
echo shortcut.TargetPath = "C:\Users\AB\mon_projet_epb\epb_smart\Lancer_EPB_Final.bat"
echo shortcut.IconLocation = "C:\Windows\System32\imageres.dll, 21"
echo shortcut.Save()
) > "%temp%\create_shortcut.vbs

:: Exécuter le script
cscript //nologo "%temp%\create_shortcut.vbs"

if exist "%USERPROFILE%\Desktop\EPB Port de Béjaïa.lnk" (
    echo.
    echo ========================================
    echo    ✅ RACCOURCI CRÉÉ AVEC SUCCÈS !
    echo ========================================
    echo.
    echo    📍 Raccourci sur votre Bureau
    echo    🚢 Icône : Bateau (Index 21)
    echo.
) else (
    echo.
    echo ========================================
    echo    ❌ ERREUR - Création échouée
    echo ========================================
    echo.
)

pause