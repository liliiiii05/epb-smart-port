# run_app_fixed.py
import os
import sys
import subprocess
import threading
import time
import webbrowser
import socket
import ctypes

def is_port_open(port):
    """Vérifie si le port est libre"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('127.0.0.1', port))
            return True
        except:
            return False

def start_django():
    """Démarre le serveur Django en arrière-plan"""
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 6  # SW_MINIMIZE (minimisé)
    
    # Lancer le serveur
    process = subprocess.Popen(
        [sys.executable, 'manage.py', 'runserver', '8000'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        startupinfo=startupinfo,
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    return process

def open_browser_once():
    """Ouvre le navigateur une seule fois"""
    # Attendre que le serveur soit prêt
    time.sleep(3)
    
    # Ouvrir le navigateur
    webbrowser.open('http://127.0.0.1:8000')

def main():
    # Cacher la console sur Windows
    if sys.platform == 'win32':
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    
    # Vérifier si une instance tourne déjà
    if is_port_open(8000):
        # Si serveur déjà lancé, ouvrir juste le navigateur
        webbrowser.open('http://127.0.0.1:8000')
        return
    
    # Démarrer le serveur
    process = start_django()
    
    # Ouvrir le navigateur dans un thread séparé
    threading.Thread(target=open_browser_once, daemon=True).start()
    
    # Attendre la fermeture
    try:
        process.wait()
    except:
        pass

if __name__ == "__main__":
    main()